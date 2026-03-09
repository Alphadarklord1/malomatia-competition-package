from __future__ import annotations

from fastapi import APIRouter

from app.schemas import LoginRequest, TokenResponse
from app.security import raise_not_implemented_auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    raise_not_implemented_auth("local")
