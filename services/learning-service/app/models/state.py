# services/learning-service/app/models/state.py
from typing import TypedDict, Any, List, Dict

class LearningState(TypedDict, total=False):
    # Identity / inputs
    workspace_id: str
    model_id: str
    pack_key: str
    pack_version: str
    playbook_id: str
    repo: dict  # {repo_url, ref, sparse_globs, depth}

    # Plan
    plan: dict  # {steps:[{id,type,tool_key|capability_id,params,emits,requires_kinds}]}

    # Execution products (across lanes)
    artifacts: List[dict]          # cumulative artifacts produced this run
    run_artifact_ids: List[str]    # set in main.py after persist

    # Dependency plumbing
    dep_plan: Dict[str, Dict[str, Any]]   # by step_id: {hard:[kinds], soft:[kinds], context_hint:str}
    related: Dict[str, Dict[str, Dict[str, List[dict]]]]  # by step_id: {"hard":{"kind":[...]}, "soft":{"kind":[...]}}
    hints: Dict[str, str]                 # by step_id: context_hint

    # Execution context (threaded data)
    context: Dict[str, Any]  # may include:
                             # - run_id
                             # - pack
                             # - tool_extras (e.g., {"repo_path": ...})
                             # - tool_outputs (per-step envelope for debugging/grounding)
                             # - validations (validator issues)
                             # - avc/fss/pss (domain inputs)

    # Classification & reporting
    deltas: Dict[str, Any]        # {"counts":{"new":..,"updated":..,"unchanged":..,"retired":..}}
    artifacts_diff: Dict[str, Any]

    # Telemetry
    logs: List[str]
    errors: List[str]
