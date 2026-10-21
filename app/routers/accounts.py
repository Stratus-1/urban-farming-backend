from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.security import CurrentUserDep, GatewayDep

router = APIRouter(tags=["accounts"])


class BuyerProfilePayload(BaseModel):
    business_name: str = Field(min_length=2, max_length=160)
    buyer_type: Literal["restaurant", "hotel", "organic_store", "retail_chain", "subscriber"] = (
        "retail_chain"
    )
    contact_email: str | None = Field(default=None, max_length=320)
    contact_name: str | None = Field(default=None, max_length=160)
    organization_type: str | None = Field(default=None, max_length=120)
    preferred_channel: str | None = Field(default=None, max_length=120)
    operating_region: str | None = Field(default=None, max_length=120)
    target_integration: str | None = Field(default=None, max_length=120)


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


@router.get("/account/buyer-profile")
async def get_buyer_profile(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    if not user.has_any_role("buyer", "admin", "operator"):
        raise AppError(403, "buyer_profile_forbidden", "Buyer account access is required")
    profile = await gateway.select(
        "buyer_profiles", token=user.access_token, filters={"user_id": user.id}, single=True
    )
    return {"profile": profile}


@router.put("/account/buyer-profile")
async def save_buyer_profile(
    payload: BuyerProfilePayload, gateway: GatewayDep, user: CurrentUserDep
) -> dict:
    if not user.has_any_role("buyer", "admin", "operator"):
        raise AppError(403, "buyer_profile_forbidden", "Buyer account access is required")

    values = payload.model_dump(exclude_none=True)
    values["user_id"] = str(user.id)
    if not values.get("contact_email"):
        values["contact_email"] = user.email
    rows = await gateway.insert(
        "buyer_profiles",
        values,
        token=user.access_token,
        upsert=True,
        on_conflict="user_id",
    )
    return {"profile": rows[0] if rows else None}


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
