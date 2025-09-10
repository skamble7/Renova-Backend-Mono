from pydantic import BaseModel, Field
from typing import List, Dict

# ---- Inputs
class ParseIn(BaseModel):
    sources: List[str] = Field(..., description="COBOL program sources (full text)")
    dialect: str = Field("ANSI85", pattern="^(ANSI85|MF|OSVS)$")

class CopybookIn(BaseModel):
    copybooks: List[str] = Field(..., description="COBOL copybook sources (full text)")

# ---- Outputs
class ParseOut(BaseModel):
    programs: List[Dict]  # JSON AST/ASG per program

class CopybookOut(BaseModel):
    xmlDocs: List[str]    # cb2xml XML strings, one per input
