from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    # Mongo
    MONGO_URI: str
    MONGO_DB: str = "renova"  # align with other Renova services

    # Downstream services — match docker-compose service names & ports
    CAPABILITY_REGISTRY_URL: str = "http://renova-capability-registry:9012"
    ARTIFACT_SERVICE_URL: str = "http://renova-artifact-service:9011"

    # Connectors (inside compose network)
    GITHUB_FETCHER_BASE_URL: str = "http://renova-github-fetcher:8080"
    PROLEAP_PARSER_BASE_URL: str = "http://renova-proleap-cb2xml:8080"

    # For dev, default to host-exposed stubs; override in .env/CI if different
    PARSER_JCL_BASE_URL: str = "http://host.docker.internal:9080"
    ANALYZER_DB2_BASE_URL: str = "http://host.docker.internal:9081"

    # Shared landing zone (same volume mounted into fetcher/parser/executor)
    LANDING_ZONE: str = "/landing_zone"
    LANDING_SUBDIR_PREFIX: str = ""  # keep empty if you prefer raw workspace ids

    # Messaging (reuse Raina’s broker + exchange as in compose)
    RABBITMQ_URI: str
    RABBITMQ_EXCHANGE: str = "raina.events"   # must match compose
    EVENTS_ORG: str = "renova"                # routing key org segment

    # LLM
    MODEL_ID: str = "openai:gpt-4o-mini"      # used by your nodes
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None        # optional (Azure/proxy)
    OPENAI_MODEL: str = "gpt-4o-mini"         # handy alias for agents that read OPENAI_MODEL

    # Service metadata
    SERVICE_NAME: str = "learning-service"
    PORT: int = 9013
    ENV: str = "local"
    REQUEST_TIMEOUT_S: int = 60

    # Pack defaults (match your pack)
    PACK_KEY: str = "pack.cobol.relearn"
    PACK_VERSION: str = "1.2.0"               # <-- drop leading 'v'
    PLAYBOOK_ID: str = "pb.cobol.relearn.v1.2"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("MONGO_URI")
    @classmethod
    def _no_placeholder_uri(cls, v: str) -> str:
        if "://" not in v:
            raise ValueError("MONGO_URI must be a valid connection string")
        return v

settings = Settings()  # type: ignore
