from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Service identity
    service_name: str
    service_port: int

    # Mongo
    mongo_uri: str
    mongo_db: str

    # Rabbit
    rabbitmq_uri: str
    rabbitmq_exchange: str
    events_org: str

    # Upstream services
    capability_service_base_url: str
    artifact_service_base_url: str

    # HTTP client defaults
    http_client_timeout_seconds: float

    # LLM
    openai_api_key: str | None
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    llm_strict_json: bool

    # MCP invocation
    mcp_http_timeout: float
    mcp_stdio_kill_timeout: int
    mcp_stdio_startup_timeout: int
    mcp_retry_max_attempts: int
    mcp_retry_backoff_ms: int

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            service_name=os.getenv("SERVICE_NAME", "learning-service"),
            service_port=int(os.getenv("SERVICE_PORT", "9013")),

            mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            mongo_db=os.getenv("MONGO_DB", "renova"),

            rabbitmq_uri=os.getenv("RABBITMQ_URI", "amqp://raina:raina@host.docker.internal:5672/"),
            rabbitmq_exchange=os.getenv("RABBITMQ_EXCHANGE", "raina.events"),
            events_org=os.getenv("EVENTS_ORG", "renova"),

            capability_service_base_url=os.getenv("CAPABILITY_SERVICE_BASE_URL", "http://localhost:9012"),
            artifact_service_base_url=os.getenv("ARTIFACT_SERVICE_BASE_URL", "http://localhost:9011"),

            http_client_timeout_seconds=float(os.getenv("HTTP_CLIENT_TIMEOUT_SECONDS", "30")),

            openai_api_key=os.getenv("OPENAI_API_KEY"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4000")),
            llm_strict_json=os.getenv("LLM_STRICT_JSON", "1") in ("1", "true", "True"),

            mcp_http_timeout=float(os.getenv("MCP_HTTP_TIMEOUT", "60")),
            mcp_stdio_kill_timeout=int(os.getenv("MCP_STDIO_KILL_TIMEOUT", "10")),
            mcp_stdio_startup_timeout=int(os.getenv("MCP_STDIO_STARTUP_TIMEOUT", "60")),
            mcp_retry_max_attempts=int(os.getenv("MCP_RETRY_MAX_ATTEMPTS", "2")),
            mcp_retry_backoff_ms=int(os.getenv("MCP_RETRY_BACKOFF_MS", "250")),
        )


# Global settings singleton
settings = Settings.from_env()
