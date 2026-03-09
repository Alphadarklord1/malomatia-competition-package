from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.schemas import ApiMessage, NotificationsResponse
from app.security import CurrentUser, get_current_user
from app.service import acknowledge_notification, list_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationsResponse)
def get_notifications(
    include_acked: bool = Query(default=False),
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> NotificationsResponse:
    return NotificationsResponse(items=list_notifications(session, include_acked=include_acked))


@router.post("/{notification_id}/ack", response_model=ApiMessage)
def ack_notification(
    notification_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiMessage:
    item = acknowledge_notification(session, notification_id, current_user)
    return ApiMessage(message="Notification acknowledged", metadata={"notification_id": item.notification_id})
