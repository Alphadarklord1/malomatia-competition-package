from __future__ import annotations

from fastapi import HTTPException, status


class AuthNotImplementedError(RuntimeError):
    pass


def raise_not_implemented_auth(provider: str = "local") -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{provider} authentication is not wired in the production scaffold yet.",
    )
