import ipaddress
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DEFAULT_JWT_SECRET = "dev-only-insecure-secret-change-in-production-32bytes"
LOCAL_LLM_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "ollama", "vllm", "host.docker.internal"})


def is_private_or_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return False
    if host in LOCAL_LLM_HOSTS or host.endswith((".local", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "ISLA Institutional AI Agent"
    debug: bool = False

    database_url: str = "sqlite:///./isla_ai_dev.db"

    jwt_secret_key: str = Field(default=DEV_DEFAULT_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Autenticação institucional (LDAP API — X-API-Key mantido estritamente no backend)
    auth_mode: Literal["local", "hybrid", "institutional"] = "hybrid"
    institutional_auth_base_url: str = "https://cksi-dev.islagaia.pt"
    institutional_auth_api_key: str = ""
    institutional_auth_origin: str = "http://localhost:5173"
    institutional_auth_timeout_seconds: float = 15.0

    # Portal Científico API — mantido estritamente no backend
    portal_api_base_url: str = "http://localhost:8000"
    portal_api_publications_path: str = "/api/powerbi/publications"
    portal_api_token: str = ""
    portal_api_timeout_seconds: float = 60.0
    portal_auto_sync_enabled: bool = True
    portal_auto_sync_interval_minutes: int = 720  # 12h (alinhado com X-PowerBI-Cache-TTL)

    max_excel_upload_mb: int = 20
    conversation_retention_days: int = 365
    reports_output_dir: str = "./reports_output"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    llm_provider: Literal["unconfigured", "deterministic", "openai_compatible"] = "unconfigured"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_allow_external_endpoints: bool = False
    llm_timeout_seconds: float = 45.0
    llm_max_tool_steps: int = 5

    @field_validator("auth_mode", "llm_provider", mode="before")
    @classmethod
    def normalize_enum_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if (
            self.llm_provider == "openai_compatible"
            and not self.llm_allow_external_endpoints
            and not is_private_or_local_url(self.llm_base_url)
        ):
            raise ValueError(
                "Por conformidade RGPD/NIS2, LLM_BASE_URL deve apontar para um servidor local ou "
                "rede privada (ex.: http://localhost:11434/v1). Defina LLM_ALLOW_EXTERNAL_ENDPOINTS=true "
                "apenas mediante aprovação institucional formal."
            )

        if self.app_env.strip().lower() in {"production", "prod"}:
            secret = self.jwt_secret_key.strip()
            if (
                secret == DEV_DEFAULT_JWT_SECRET
                or "CHANGE_ME" in secret.upper()
                or len(secret) < 32
                or len(set(secret)) < 12
            ):
                raise ValueError(
                    "Em produção, JWT_SECRET_KEY deve ser um segredo aleatório de alta entropia "
                    '(>= 32 caracteres). Gere com: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if self.debug:
                raise ValueError("DEBUG não pode estar ativo em produção.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
