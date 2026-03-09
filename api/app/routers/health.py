from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    database_mode = "postgresql"
    if settings.database_url.startswith("sqlite"):
        database_mode = "sqlite"
    return HealthResponse(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database_mode=database_mode,
    )
