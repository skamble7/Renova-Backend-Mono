# services/learning-service/app/diagrams/generator.py
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable, Tuple

from app.llms.base import LLMRequest
from app.llms.registry import build_provider_from_llm_config

log = logging.getLogger("app.diagrams.generator")

# Prompt sizing
_MAX_DATA_CHARS = 16000     # overall guardrail
_CHUNK_TARGET = 9000        # per-LLM call payload target (leave room for instructions/tokens)
_MIN_CHUNK = 4000           # don't over-fragment tiny payloads
_PREVIEW_CHARS = 600        # how many instruction chars to log

# Optional: dump final mermaid to files for offline inspection
def _truthy_env(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "y", "on"}

_DUMP_ENABLED = _truthy_env(os.getenv("DIAGRAM_DEBUG_DUMP"))
_DUMP_DIR = Path(os.getenv("DIAGRAM_DEBUG_DIR", "/workspace/.renova/debug/diagrams")).resolve()
_DUMP_DIR.mkdir(parents=True, exist_ok=True) if _DUMP_ENABLED else None


def _minify_json(obj: Any) -> str:
    try:
        return json.dumps(obj or {}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _preview(s: str, n: int = _PREVIEW_CHARS) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: n - 20] + "... <truncated>")


def _sanitize_mermaid(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        # strip code fences
        s = re.sub(r"^```[a-zA-Z0-9]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _strip_mermaid_directive(body: str) -> str:
    """Remove any leading diagram directive if the model repeats it in later chunks."""
    s = _sanitize_mermaid(body)
    s = re.sub(
        r"^(flowchart\s+(TD|LR|BT|RL)\b|sequenceDiagram\b|mindmap\b|classDiagram\b|stateDiagram\b|erDiagram\b)[^\n]*\n?",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return s.strip()


def _is_valid_mermaid(text: str, view: Optional[str] = None) -> bool:
    if not isinstance(text, str):
        return False
    s = _sanitize_mermaid(text)
    if not s:
        return False

    v = (view or "").strip().lower()

    if v in {"sequence", "sequencediagram"}:
        return bool(s.startswith("sequenceDiagram"))

    if v in {"flow", "flowchart"}:
        return bool(re.match(r"^flowchart\s+(TD|LR|BT|RL)\b", s, flags=re.IGNORECASE))

    if v == "mindmap":
        return s.startswith("mindmap")

    return bool(re.match(r"^(flowchart|sequenceDiagram|mindmap|classDiagram|stateDiagram|erDiagram)\b", s))


def _chunk_paragraphs(paragraphs: List[Dict[str, Any]], approx_json_budget: int) -> List[List[Dict[str, Any]]]:
    sample = paragraphs[:50]
    try:
        avg_len = max(1, len(_minify_json(sample)) // max(1, len(sample) or 1))
    except Exception:
        avg_len = 512
    per_chunk = max(10, min(200, (approx_json_budget // max(1, avg_len)) or 50))

    out = []
    it = iter(paragraphs)
    while True:
        batch = list(islice(it, per_chunk))
        if not batch:
            break
        out.append(batch)
    return out or [paragraphs]


def _split_artifact_for_prompt(data: Dict[str, Any], view: str) -> List[Tuple[str, Dict[str, Any]]]:
    full = _minify_json(data)
    if len(full) <= _CHUNK_TARGET or len(full) < _MIN_CHUNK:
        return [("chunk-1", data)]

    if isinstance(data.get("paragraphs"), list) and data["paragraphs"]:
        base = {k: v for k, v in data.items() if k != "paragraphs"}
        budget = max(1024, _CHUNK_TARGET - len(_minify_json(base)) - 1000)
        groups = _chunk_paragraphs(data["paragraphs"], budget)
        chunks = []
        for i, grp in enumerate(groups, 1):
            chunk = dict(base)
            chunk["paragraphs"] = grp
            chunks.append((f"paragraphs-{i}", chunk))
        return chunks

    slices = []
    s = full
    i = 0
    while s:
        part, s = s[:_CHUNK_TARGET], s[_CHUNK_TARGET:]
        i += 1
        slices.append((f"slice-{i}", {"_slice": part}))
    return slices


def _build_view_header(view: str) -> str:
    v = (view or "").strip().lower()
    if v in {"flow", "flowchart", ""}:
        return "flowchart TD"
    if v in {"sequence", "sequencediagram"}:
        return "sequenceDiagram"
    if v == "mindmap":
        return "mindmap"
    if v == "class":
        return "classDiagram"
    if v in {"state", "statediagram"}:
        return "stateDiagram"
    if v in {"er", "erdiagram"}:
        return "erDiagram"
    return "flowchart TD"


def _cobol_hints(data: Dict[str, Any]) -> Optional[str]:
    if "paragraphs" in (data or {}):
        return (
            "- If data.paragraphs exists, create one node per paragraph name.\n"
            "- For each paragraph p, draw an edge from p to each target in p.performs.\n"
            "- Sanitize node IDs by replacing hyphens with underscores.\n"
            "- Add START and END only if it clarifies flow."
        )
    return None


async def _emit_mermaid_chunked(
    *,
    view: str,
    data_chunks: List[Tuple[str, Dict[str, Any]]],
    llm_config: Optional[Dict[str, Any]],
    dump_key: Optional[str] = None,
) -> Optional[str]:
    provider, req_defaults = build_provider_from_llm_config(llm_config or {})
    base_kwargs = dict(req_defaults or {})
    for k in ("system_prompt", "user_prompt", "json_schema", "strict_json"):
        base_kwargs.pop(k, None)
    temperature = base_kwargs.pop("temperature", 0.1)
    max_tokens = base_kwargs.pop("max_tokens", 1200)

    view_header = _build_view_header(view)
    general_rules = [
        "Output Mermaid only. No prose. No code fences.",
        "Use stable, explicit identifiers. Avoid truncation.",
        "If this is NOT the first chunk, DO NOT include the diagram directive; only append lines that fit under the same diagram.",
    ]
    domain_hints = _cobol_hints(data_chunks[0][1])
    if domain_hints:
        general_rules.append(domain_hints)

    composed: List[str] = []
    for i, (label, chunk_data) in enumerate(data_chunks, start=1):
        is_first = i == 1
        system = "You emit Mermaid only. No prose, no code fences. Be precise and deterministic."

        rules = "\n".join(f"- {r}" for r in general_rules)
        chunk_json = _minify_json(chunk_data)
        prefix = f"VIEW: {view_header}\nCHUNK: {i}/{len(data_chunks)} ({label})\n\nConstraints:\n{rules}\n"

        log.debug(
            "diagram.emit.request",
            extra={
                "view_header": view_header,
                "chunk_index": i,
                "chunk_label": label,
                "total_chunks": len(data_chunks),
                "json_size": len(chunk_json),
            },
        )

        ask = (
            f"{prefix}\nArtifact JSON data for this chunk:\n{chunk_json}\n\n"
            + ("Start with the diagram directive line.\n" if is_first else "Do NOT repeat the diagram directive.\n")
            + "Return Mermaid ONLY."
        )

        req = LLMRequest(
            system_prompt=system,
            user_prompt=ask,
            json_schema=None,
            strict_json=False,  # we want plain text (Mermaid), not JSON
            temperature=temperature,
            max_tokens=max_tokens,
            **base_kwargs,
        )
        try:
            # Prefer a text endpoint if available; otherwise rely on provider honoring strict_json=False.
            if hasattr(provider, "acomplete_text"):
                raw = await provider.acomplete_text(req)
            else:
                raw = await provider.acomplete_json(req)
        except Exception:
            log.error(
                "diagram.emit.error",
                extra={"view_header": view_header, "chunk_index": i, "chunk_label": label},
                exc_info=True,
            )
            return None

        # Some providers might return dict/list; coerce to string defensively
        if isinstance(raw, dict):
            s = _sanitize_mermaid(str(raw.get("text") or ""))
            shape = "dict"
        elif isinstance(raw, list):
            s = _sanitize_mermaid("\n".join(map(str, raw)))
            shape = "list"
        else:
            s = _sanitize_mermaid(str(raw))
            shape = type(raw).__name__

        log.info(
            "diagram.emit.chunk",
            extra={
                "view_header": view_header,
                "chunk_index": i,
                "chunk_label": label,
                "provider_shape": shape,
                "instr_len": len(s),
                "instr_preview": _preview(s),
            },
        )

        if not s:
            log.warning(
                "diagram.emit.empty",
                extra={"view_header": view_header, "chunk_index": i, "chunk_label": label},
            )
            return None
        if not is_first:
            s = _strip_mermaid_directive(s)
        composed.append(s)

    merged = []
    for j, part in enumerate(composed, start=1):
        if j == 1:
            merged.append(part)
        else:
            merged.append(_strip_mermaid_directive(part))
    final = "\n".join(merged).strip()

    log.info(
        "diagram.emit.final",
        extra={"view_header": view_header, "final_len": len(final), "final_preview": _preview(final, 1000)},
    )

    if _DUMP_ENABLED:
        try:
            stem = f"{dump_key or uuid.uuid4().hex}_{view_header.split()[0].lower()}"
            path = _DUMP_DIR / f"{stem}.mmd"
            path.write_text(final, encoding="utf-8")
            log.info("diagram.dump.saved", extra={"path": str(path), "bytes": len(final)})
        except Exception:  # never break the run on dump issues
            log.warning("diagram.dump.failed", exc_info=True)

    return final


async def generate_diagrams_for_artifact(
    *,
    kind_doc: Dict[str, Any],
    data: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None,
    dump_key: Optional[str] = None,  # e.g., f"{run_id}_{artifact_name}"
) -> List[Dict[str, Any]]:
    """
    Read the kind's latest schema version and produce Mermaid diagrams using ONLY the recipe `view`.
    - Templates are ignored for now.
    - If the artifact data is large, we chunk and compose one diagram per recipe.
    """
    latest = str(kind_doc.get("latest_schema_version") or "1.0.0")
    sv = next((x for x in (kind_doc.get("schema_versions") or []) if str(x.get("version")) == latest), {}) or {}
    recipes = list(sv.get("diagram_recipes") or [])

    if not recipes:
        log.debug("diagram.no_recipes", extra={"kind_id": kind_doc.get("id")})
        return []

    out: List[Dict[str, Any]] = []
    for r in recipes:
        language = (r.get("language") or "mermaid").lower()
        if language != "mermaid":
            log.debug("diagram.skip.language", extra={"recipe": r.get("id") or r.get("name"), "language": language})
            continue

        view = str(r.get("view") or "").strip().lower() or "flowchart"
        chunks = _split_artifact_for_prompt(data or {}, view)
        instr = await _emit_mermaid_chunked(view=view, data_chunks=chunks, llm_config=llm_config, dump_key=dump_key)
        if not instr:
            log.warning(
                "diagram.skip.no_instructions",
                extra={"recipe": r.get("id") or r.get("name"), "view": view, "chunks": len(chunks)},
            )
            continue

        if not _is_valid_mermaid(instr, view=view):
            header = _build_view_header(view)
            candidate = f"{header}\n{_strip_mermaid_directive(instr)}"
            if not _is_valid_mermaid(candidate, view=view):
                log.warning(
                    "diagram.skip.invalid_mermaid",
                    extra={
                        "recipe": r.get("id") or r.get("name"),
                        "view": view,
                        "len": len(instr),
                        "preview": _preview(instr),
                    },
                )
                continue
            instr = candidate

        entry = {
            "id": r.get("id") or r.get("name") or f"diagram-{len(out)+1}",
            "title": r.get("title") or r.get("id") or r.get("name") or f"{view.title()}",
            "view": r.get("view") or view,
            "language": "mermaid",
            "instructions": _sanitize_mermaid(instr),
            "renderer_hints": r.get("renderer_hints") or {},
        }
        log.info(
            "diagram.accepted",
            extra={
                "recipe": entry["id"],
                "view": entry["view"],
                "len": len(entry["instructions"]),
                "preview": _preview(entry["instructions"]),
            },
        )
        out.append(entry)

    if not out:
        log.info("diagram.none_emitted", extra={"recipes": len(recipes)})

    return out
