from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.audit import append_audit_event
from app.db import get_session
from app.models import User
from app.schemas import LoginRequest, LoginResponse, MfaVerifyRequest, RegisterRequest, RegisterResponse, UserProfile
from app.security import (
    CurrentUser,
    authenticate_local_user,
    clear_login_failures,
    create_access_token,
    create_pending_mfa_token,
    decode_token,
    generate_totp_secret,
    get_current_user,
    get_local_user,
    hash_password,
    is_user_locked,
    provisioning_uri,
    register_failed_login,
    verify_totp_code,
)
from app.workflow_rules import utc_now

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    username = payload.username.strip()
    user = get_local_user(session, username)
    if user is None:
        append_audit_event(
            session,
            user_id=username or "anonymous",
            role="unauthenticated",
            action="login",
            result="failure",
            details={"reason": "invalid_credentials"},
            timestamp=utc_now(),
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.status == "pending":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account awaiting supervisor approval")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    if is_user_locked(user):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")

    authenticated = authenticate_local_user(session, username, payload.password)
    if authenticated is None:
        register_failed_login(session, user)
        append_audit_event(
            session,
            user_id=username,
            role=user.role,
            action="login",
            result="failure",
            details={"reason": "invalid_credentials"},
            timestamp=utc_now(),
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    clear_login_failures(session, user)
    if user.mfa_enabled and user.mfa_secret:
        pending_token, expires_in = create_pending_mfa_token(user=user)
        append_audit_event(
            session,
            user_id=user.user_id,
            role=user.role,
            action="login",
            result="mfa_required",
            details={"auth_provider": user.auth_provider},
            timestamp=utc_now(),
        )
        session.commit()
        return LoginResponse(
            expires_in=expires_in,
            role=user.role,
            mfa_required=True,
            pending_token=pending_token,
            message="Verification code required",
        )

    token, expires_in = create_access_token(user=user)
    user.last_login_at_utc = utc_now()
    session.add(user)
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
    return LoginResponse(access_token=token, expires_in=expires_in, role=user.role)


@router.post("/mfa/verify", response_model=LoginResponse)
def verify_mfa(payload: MfaVerifyRequest, session: Session = Depends(get_session)) -> LoginResponse:
    pending_payload = decode_token(payload.pending_token, expected_type="mfa")
    user_id = str(pending_payload.get("sub") or "")
    user = get_local_user(session, user_id)
    if user is None or user.status != "active" or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA session invalid")
    if not verify_totp_code(user.mfa_secret, payload.code):
        append_audit_event(
            session,
            user_id=user.user_id,
            role=user.role,
            action="mfa_verify",
            result="failure",
            details={"reason": "invalid_code"},
            timestamp=utc_now(),
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid verification code")

    clear_login_failures(session, user)
    token, expires_in = create_access_token(user=user)
    user.last_login_at_utc = utc_now()
    session.add(user)
    append_audit_event(
        session,
        user_id=user.user_id,
        role=user.role,
        action="mfa_verify",
        result="success",
        details={},
        timestamp=utc_now(),
    )
    session.commit()
    return LoginResponse(access_token=token, expires_in=expires_in, role=user.role)


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest, session: Session = Depends(get_session)) -> RegisterResponse:
    username = payload.username.strip()
    display_name = payload.display_name.strip()
    existing = get_local_user(session, username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

    now = utc_now()
    mfa_secret = generate_totp_secret() if payload.enable_mfa else None
    user = User(
        user_id=username,
        display_name=display_name,
        auth_provider="local",
        role="operator",
        status="pending",
        password_hash=hash_password(payload.password),
        failed_login_attempts=0,
        locked_until_utc=None,
        mfa_enabled=bool(mfa_secret),
        mfa_secret=mfa_secret,
        last_login_at_utc=None,
        created_at_utc=now,
        updated_at_utc=now,
    )
    session.add(user)
    append_audit_event(
        session,
        user_id=username,
        role="operator",
        action="register",
        result="pending",
        details={"mfa_enabled": bool(mfa_secret)},
        timestamp=now,
    )
    session.commit()
    return RegisterResponse(
        user_id=username,
        status="pending",
        mfa_secret=mfa_secret,
        provisioning_uri=provisioning_uri(user_id=username, secret=mfa_secret) if mfa_secret else None,
        message="Account created and waiting for supervisor approval",
    )


@router.get("/me", response_model=UserProfile)
def me(current_user: CurrentUser = Depends(get_current_user)) -> UserProfile:
    return UserProfile(
        user_id=current_user.user_id,
        display_name=current_user.display_name,
        role=current_user.role,
        auth_provider=current_user.auth_provider,
        status=current_user.status,
        mfa_enabled=current_user.mfa_enabled,
    )
