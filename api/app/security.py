from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

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
        self.status = user.status
        self.mfa_enabled = user.mfa_enabled


class AuthNotImplementedError(RuntimeError):
    pass


def hash_password(password: str, *, iterations: int = 210000) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode('utf-8')}${base64.b64encode(derived).decode('utf-8')}"


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


def _create_token(payload: dict[str, Any], *, expires_seconds: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    full_payload = {
        **payload,
        "exp": int((now + timedelta(seconds=expires_seconds)).timestamp()),
        "iat": int(now.timestamp()),
    }
    return jwt.encode(full_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(*, user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_in = int(settings.jwt_access_token_minutes * 60)
    token = _create_token(
        {
            "sub": user.user_id,
            "role": user.role,
            "provider": user.auth_provider,
            "type": "access",
        },
        expires_seconds=expires_in,
    )
    return token, expires_in


def create_pending_mfa_token(*, user: User) -> tuple[str, int]:
    expires_in = 300
    token = _create_token(
        {
            "sub": user.user_id,
            "role": user.role,
            "provider": user.auth_provider,
            "type": "mfa",
        },
        expires_seconds=expires_in,
    )
    return token, expires_in


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc
    token_type = str(payload.get("type") or "")
    if token_type != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token type mismatch")
    return payload


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def provisioning_uri(*, user_id: str, secret: str, issuer: str = "Malomatia Gov Triage") -> str:
    account = user_id.replace(" ", "%20")
    issuer_enc = issuer.replace(" ", "%20")
    return f"otpauth://totp/{issuer_enc}:{account}?secret={secret}&issuer={issuer_enc}"


def _totp_counter(now: datetime, *, interval_seconds: int = 30) -> int:
    return int(now.timestamp() // interval_seconds)


def _normalize_totp_secret(secret: str) -> bytes:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode((secret.upper() + padding).encode("utf-8"))


def _hotp(secret: str, counter: int, *, digits: int = 6) -> str:
    key = _normalize_totp_secret(secret)
    message = counter.to_bytes(8, "big")
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def verify_totp_code(secret: str, code: str, *, now: datetime | None = None, window: int = 1) -> bool:
    normalized_code = "".join(ch for ch in code if ch.isdigit())
    if len(normalized_code) != 6:
        return False
    current_time = now or datetime.now(timezone.utc)
    counter = _totp_counter(current_time)
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + drift), normalized_code):
            return True
    return False


def get_local_user(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.user_id == username, User.auth_provider == "local")).first()


def is_user_locked(user: User, *, now: datetime | None = None) -> bool:
    if user.locked_until_utc is None:
        return False
    current_time = now or datetime.now(timezone.utc)
    locked_until = user.locked_until_utc
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > current_time



def register_failed_login(session: Session, user: User, *, threshold: int = 5, lockout_minutes: int = 15) -> None:
    now = datetime.now(timezone.utc)
    user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= threshold:
        user.locked_until_utc = now + timedelta(minutes=lockout_minutes)
        user.failed_login_attempts = 0
    user.updated_at_utc = now
    session.add(user)



def clear_login_failures(session: Session, user: User) -> None:
    now = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.locked_until_utc = None
    user.updated_at_utc = now
    session.add(user)



def authenticate_local_user(session: Session, username: str, password: str) -> User | None:
    user = get_local_user(session, username)
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
    payload = decode_token(credentials.credentials, expected_type="access")
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
