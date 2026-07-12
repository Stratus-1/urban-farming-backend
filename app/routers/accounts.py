from fastapi import APIRouter

from app.core.security import CurrentUserDep, GatewayDep

router = APIRouter(tags=["accounts"])


@router.get("/profile")
async def get_profile(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    profile = await gateway.select(
        "profiles", token=user.access_token, filters={"id": user.id}, single=True
    )
    settings = await gateway.select(
        "user_settings", token=user.access_token, filters={"user_id": user.id}, single=True
    )
    stats = await gateway.select(
        "grower_stats", token=user.access_token, filters={"user_id": user.id}, single=True
    )
    return {"profile": profile, "settings": settings, "stats": stats, "roles": sorted(user.roles)}


@router.patch("/profile/settings")
async def update_settings(payload: dict, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    allowed = {
        "phone",
        "address",
        "bio",
        "language",
        "timezone",
        "theme",
        "email_notifications",
        "push_notifications",
        "weekly_digest",
        "task_reminders",
        "profile_locked",
        "activity_tracking",
    }
    sanitized = {key: value for key, value in payload.items() if key in allowed}
    rows = await gateway.insert(
        "user_settings",
        {"user_id": str(user.id), **sanitized},
        token=user.access_token,
        upsert=True,
        on_conflict="user_id",
    )
    return rows[0]
