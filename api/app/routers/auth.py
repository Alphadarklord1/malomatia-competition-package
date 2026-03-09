from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.audit import append_audit_event
from app.db import get_session
from app.schemas import LoginRequest, TokenResponse, UserProfile
from app.security import authenticate_local_user, create_access_token, get_current_user, CurrentUser
from app.workflow_rules import utc_now

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate_local_user(session, payload.username.strip(), payload.password)
    if user is None:
        append_audit_event(
            session,
            user_id=payload.username.strip() or "anonymous",
            role="unauthenticated",
            action="login",
            result="failure",
            details={"reason": "invalid_credentials"},
            timestamp=utc_now(),
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, expires_in = create_access_token(user=user)
    append_audit_event(
        session,
        user_id=user.user_id,
        role=user.role,
        action="login",
        result="success",
        details={"auth_provider": user.auth_provider},
        timestamp=utc_now(),
    )
    session.commit()
    return TokenResponse(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/me", response_model=UserProfile)
def me(current_user: CurrentUser = Depends(get_current_user)) -> UserProfile:
    return UserProfile(
        user_id=current_user.user_id,
        display_name=current_user.display_name,
        role=current_user.role,
        auth_provider=current_user.auth_provider,
    )
