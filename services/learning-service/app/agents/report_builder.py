from __future__ import annotations

from datetime import datetime
from typing import Dict, List


def run_header_md(run_meta: Dict[str, str]) -> str:
    return (
        f"# Learning Run\n"
        f"- **Run ID**: {run_meta.get('run_id')}\n"
        f"- **Workspace**: {run_meta.get('workspace_id')}\n"
        f"- **Pack**: {run_meta.get('pack_id')}\n"
        f"- **Playbook**: {run_meta.get('playbook_id')}\n"
        f"- **Strategy**: {run_meta.get('strategy')}\n"
        f"- **Started**: {run_meta.get('started_at')}\n\n"
        f"---\n\n"
    )


def step_summary_md(step_id: str, name: str, stats: Dict[str, int], notes: str = "") -> str:
    lines = [
        f"## Step: {name} ({step_id})",
        "",
        f"- Produced: {stats.get('produced_total', 0)} artifact(s)",
        f"- Added: {stats.get('added', 0)}, Changed: {stats.get('changed', 0)}, Unchanged: {stats.get('unchanged', 0)}",
        "",
    ]
    if notes:
        lines.append(notes.strip())
        lines.append("")
    return "\n".join(lines) + "\n"


def artifact_counts_md(total_by_kind: Dict[str, int]) -> str:
    if not total_by_kind:
        return "### Artifact Summary\n\n_No artifacts produced._\n\n"
    lines: List[str] = ["### Artifact Summary", "", "| Kind | Count |", "|---|---|"]
    for k, v in sorted(total_by_kind.items()):
        lines.append(f"| `{k}` | {v} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def run_footer_md(completed_at: datetime) -> str:
    return f"---\n\n_Completed at {completed_at.isoformat(timespec='seconds')}Z_\n"
