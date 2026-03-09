from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session
from .models import User

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user: User) -> None:
        self.user = user
        self.user_id = user.user_id
        self.role = user.role
        self.display_name = user.display_name
        self.auth_provider = user.auth_provider


class AuthNotImplementedError(RuntimeError):
    pass


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash.startswith("pbkdf2_sha256$"):
        return False
    parts = stored_hash.split("$", 3)
    if len(parts) != 4:
        return False
    _, iter_str, salt_b64, digest_b64 = parts
    try:
        iterations = int(iter_str)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected = base64.b64decode(digest_b64.encode("utf-8"))
    except Exception:
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def create_access_token(*, user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_in = int(settings.jwt_access_token_minutes * 60)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.user_id,
        "role": user.role,
        "provider": user.auth_provider,
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iat": int(now.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def authenticate_local_user(session: Session, username: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.user_id == username)).first()
    if user is None or user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc
    user_id = str(payload.get("sub") or "")
    user = session.exec(select(User).where(User.user_id == user_id)).first()
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or missing")
    return CurrentUser(user)


def require_roles(*roles: str):
    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency
