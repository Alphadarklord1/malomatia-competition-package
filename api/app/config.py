from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Malomatia Gov Triage API"
    app_version: str = "0.1.0"
    environment: str = Field(default="development")
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/malomatia")
    redis_url: str = Field(default="redis://localhost:6379/0")
    audit_sink: str = Field(default="database")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_embedding_model: str = Field(default="text-embedding-3-small")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MALOMATIA_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
