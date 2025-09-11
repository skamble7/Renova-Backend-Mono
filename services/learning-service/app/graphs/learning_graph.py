from langgraph.graph import StateGraph, END
from typing import Callable
from app.models.state import LearningState
from app.nodes.ingest_node import ingest_node
from app.nodes.plan_node import plan_node
from app.nodes.execute_node import execute_node
from app.nodes.classify_after_persist_node import classify_after_persist_node
from app.nodes.publish_node import publish_node
from app.nodes.validate_node import validate_node  # <-- add this line


def build_graph() -> Callable[[LearningState], LearningState]:
    sg = StateGraph(LearningState)

    sg.add_node("ingest", ingest_node)
    sg.add_node("plan", plan_node)
    sg.add_node("execute", execute_node)
    sg.add_node("classify", classify_after_persist_node)
    sg.add_node("publish", publish_node)
    sg.add_node("validate", validate_node)

    sg.set_entry_point("ingest")
    sg.add_edge("ingest", "plan")
    sg.add_edge("plan", "execute")
    sg.add_edge("execute", "validate")
    sg.add_edge("execute", "classify")
    sg.add_edge("classify", "publish")
    sg.add_edge("publish", END)

    return sg.compile()
