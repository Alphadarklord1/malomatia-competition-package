from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine = None


def build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, pool_pre_ping=True, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database_url)
    return _engine


def reset_engine(database_url: str | None = None) -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = build_engine(database_url or get_settings().database_url)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
