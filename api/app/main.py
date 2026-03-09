from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.config import get_settings
from app.db import get_engine, init_db
from app.routers.auth import router as auth_router
from app.routers.audit import router as audit_router
from app.routers.cases import router as cases_router
from app.routers.dashboard import router as dashboard_router
from app.routers.health import router as health_router
from app.routers.notifications import router as notifications_router
from app.routers.rag import router as rag_router
from app.routers.review import router as review_router
from app.routers.users import router as users_router
from app.seed import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    if settings.seed_demo_data:
        with Session(get_engine()) as session:
            seed_database(session)
    yield



def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(dashboard_router)
    app.include_router(cases_router)
    app.include_router(audit_router)
    app.include_router(review_router)
    app.include_router(notifications_router)
    app.include_router(rag_router)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "ok",
        }

    return app


app = create_app()
