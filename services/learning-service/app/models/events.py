# services/learning-service/app/models/events.py
from pydantic import BaseModel
from typing import Any

class Event(BaseModel):
    type: str
    workspace_id: str
    payload: Any
