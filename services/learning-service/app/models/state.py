# services/learning-service/app/models/state.py
from typing import TypedDict, Any, List, Dict

class LearningState(TypedDict, total=False):
    workspace_id: str
    model_id: str
    pack_key: str
    pack_version: str
    playbook_id: str
    repo: dict

    plan: dict
    artifacts: List[dict]
    run_artifact_ids: List[str]

    logs: List[str]
    errors: List[str]

    context: Dict[str, Any]  # runtime, tool extras, etc.
    deltas: Dict[str, Any]   # {counts:{...}}
    artifacts_diff: Dict[str, Any]
