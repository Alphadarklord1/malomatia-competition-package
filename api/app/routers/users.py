from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.audit import append_audit_event
from app.db import get_session
from app.models import User
from app.schemas import (
    ApiMessage,
    MfaSetupResponse,
    PasswordResetRequest,
    UserCreateRequest,
    UserSummary,
    UserUpdateRequest,
    UsersResponse,
)
from app.security import CurrentUser, generate_totp_secret, get_current_user, hash_password, provisioning_uri, require_roles
from app.workflow_rules import utc_now

router = APIRouter(prefix="/users", tags=["users"])


def _user_summary(user: User) -> UserSummary:
    return UserSummary(
        user_id=user.user_id,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        auth_provider=user.auth_provider,
        mfa_enabled=user.mfa_enabled,
        locked_until_utc=user.locked_until_utc,
        failed_login_attempts=user.failed_login_attempts,
    )


@router.get("", response_model=UsersResponse)
def list_users(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(require_roles("supervisor", "auditor")),
) -> UsersResponse:
    users = session.exec(select(User).order_by(User.user_id.asc())).all()
    return UsersResponse(items=[_user_summary(user) for user in users])


@router.post("", response_model=UserSummary)
def create_user(
    payload: UserCreateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles("supervisor")),
) -> UserSummary:
    if session.get(User, payload.user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    now = utc_now()
    mfa_secret = generate_totp_secret() if payload.enable_mfa else None
    user = User(
        user_id=payload.user_id,
        display_name=payload.display_name,
        auth_provider="local",
        role=payload.role,
        status=payload.status,
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
        user_id=current_user.user_id,
        role=current_user.role,
        action="create_user",
        result="success",
        details={"created_user_id": user.user_id, "role": user.role, "status": user.status},
        timestamp=now,
    )
    session.commit()
    return _user_summary(user)


@router.patch("/{user_id}", response_model=UserSummary)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles("supervisor")),
) -> UserSummary:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
    user.updated_at_utc = utc_now()
    session.add(user)
    append_audit_event(
        session,
        user_id=current_user.user_id,
        role=current_user.role,
        action="update_user",
        result="success",
        details={"target_user_id": user.user_id, "role": user.role, "status": user.status},
        timestamp=user.updated_at_utc,
    )
    session.commit()
    session.refresh(user)
    return _user_summary(user)


@router.post("/{user_id}/reset-password", response_model=ApiMessage)
def reset_password(
    user_id: str,
    payload: PasswordResetRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles("supervisor")),
) -> ApiMessage:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at_utc = utc_now()
    session.add(user)
    append_audit_event(
        session,
        user_id=current_user.user_id,
        role=current_user.role,
        action="reset_password",
        result="success",
        details={"target_user_id": user.user_id},
        timestamp=user.updated_at_utc,
    )
    session.commit()
    return ApiMessage(message="Password reset", metadata={"user_id": user.user_id})


@router.post("/{user_id}/mfa/setup", response_model=MfaSetupResponse)
def setup_mfa(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> MfaSetupResponse:
    if current_user.role != "supervisor" and current_user.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to manage MFA for this user")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    secret = generate_totp_secret()
    user.mfa_enabled = True
    user.mfa_secret = secret
    user.updated_at_utc = utc_now()
    session.add(user)
    append_audit_event(
        session,
        user_id=current_user.user_id,
        role=current_user.role,
        action="setup_mfa",
        result="success",
        details={"target_user_id": user.user_id},
        timestamp=user.updated_at_utc,
    )
    session.commit()
    return MfaSetupResponse(
        user_id=user.user_id,
        mfa_enabled=True,
        mfa_secret=secret,
        provisioning_uri=provisioning_uri(user_id=user.user_id, secret=secret),
    )


@router.post("/{user_id}/mfa/disable", response_model=ApiMessage)
def disable_mfa(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiMessage:
    if current_user.role != "supervisor" and current_user.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to manage MFA for this user")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.mfa_enabled = False
    user.mfa_secret = None
    user.updated_at_utc = utc_now()
    session.add(user)
    append_audit_event(
        session,
        user_id=current_user.user_id,
        role=current_user.role,
        action="disable_mfa",
        result="success",
        details={"target_user_id": user.user_id},
        timestamp=user.updated_at_utc,
    )
    session.commit()
    return ApiMessage(message="MFA disabled", metadata={"user_id": user.user_id})
