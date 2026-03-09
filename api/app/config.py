from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Malomatia Gov Triage API"
    app_version: str = "0.2.0"
    environment: str = Field(default="development")
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/malomatia")
    redis_url: str = Field(default="redis://localhost:6379/0")
    audit_sink: str = Field(default="database")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    cors_origins: str = Field(default="http://localhost:3000")
    jwt_secret_key: str = Field(default="malomatia-dev-secret-change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_minutes: int = Field(default=60)
    seed_demo_data: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MALOMATIA_",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
