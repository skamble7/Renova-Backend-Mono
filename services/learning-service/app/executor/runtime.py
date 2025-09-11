# services/learning-service/app/executor/runtime.py
from __future__ import annotations
from typing import Dict, Any
from app.config import settings

def make_runtime_config(workspace_name: str) -> Dict[str, Any]:
    landing_subdir = f"{settings.LANDING_SUBDIR_PREFIX}{workspace_name}"
    return {
        "connectors": {
            "fetcher.scm.github": {
                "base_url": settings.GITHUB_FETCHER_BASE_URL,
                "landing_zone": settings.LANDING_ZONE,
            },
            "parser.cobol.proleap": {
                "base_url": settings.PROLEAP_PARSER_BASE_URL,
                "landing_zone": settings.LANDING_ZONE,
            },
            "parser.jcl.example": { "base_url": settings.PARSER_JCL_BASE_URL },
            "analyzer.db2.example": { "base_url": settings.ANALYZER_DB2_BASE_URL },
        },
        "workspace": {
            "name": workspace_name,
            "landing_subdir": landing_subdir,
        },
    }
