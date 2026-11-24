from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "ISLA Institutional AI Agent"
    debug: bool = False

    database_url: str = "sqlite:///./isla_ai_dev.db"

    jwt_secret_key: str = Field(
        default="dev-only-insecure-secret-change-in-production-32bytes"
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Autenticação institucional (LDAP API — X-API-Key mantido estritamente no backend)
    auth_mode: str = "hybrid"  # hybrid | institutional | local
    institutional_auth_base_url: str = "https://auth.dariosoares.dev"
    institutional_auth_api_key: str = ""
    institutional_auth_origin: str = "http://localhost:5173"
    institutional_auth_timeout_seconds: float = 15.0
    institutional_auth_allow_students: bool = False

    # Portal Científico API — mantido estritamente no backend
    portal_api_base_url: str = "http://localhost:8000"
    portal_api_publications_path: str = "/api/powerbi/publications"
    portal_api_token: str = ""
    portal_api_timeout_seconds: float = 60.0

    max_excel_upload_mb: int = 20
    conversation_retention_days: int = 365
    reports_output_dir: str = "./reports_output"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    llm_provider: str = "unconfigured"
    llm_model: str = ""
    llm_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
