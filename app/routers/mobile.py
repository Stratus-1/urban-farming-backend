from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import Field

from app.core.errors import AppError
from app.core.security import AdminUserDep, CurrentUserDep, GatewayDep
from app.schemas.common import APIModel
from app.schemas.communications import MobilePushNotificationCreate
from app.services.mobile_push import send_push_to_audience

router = APIRouter(prefix="/mobile", tags=["mobile"])


class PushTokenUpsert(APIModel):
    token: str = Field(min_length=32, max_length=512)
    platform: str = Field(min_length=1, max_length=40)
    device_name: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=40)


@router.post("/push-tokens")
async def upsert_push_token(
    payload: PushTokenUpsert, gateway: GatewayDep, user: CurrentUserDep
) -> dict:
    rows = await gateway.insert(
        "mobile_push_tokens",
        {
            "user_id": str(user.id),
            "token": payload.token.strip(),
            "platform": payload.platform.strip(),
            "device_name": payload.device_name.strip() if payload.device_name else None,
            "app_version": payload.app_version.strip() if payload.app_version else None,
            "last_seen_at": datetime.now(UTC).isoformat(),
        },
        token=user.access_token,
        upsert=True,
        on_conflict="token",
    )
    return rows[0]


@router.post("/notifications/send")
async def send_push_notification(
    payload: MobilePushNotificationCreate,
    request: Request,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    if not payload.user_ids and not payload.roles:
        raise AppError(
            422,
            "missing_push_audience",
            "Provide at least one user id or role for push delivery",
        )

    settings = request.app.state.settings
    result = await send_push_to_audience(
        settings=settings,
        gateway=gateway,
        token=user.access_token,
        title=payload.title,
        body=payload.body,
        user_ids=payload.user_ids or None,
        roles=payload.roles or None,
        data=payload.data or None,
        image_url=payload.image_url,
    )
    return {"ok": True, **result}
