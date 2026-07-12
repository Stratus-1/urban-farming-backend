import asyncio
from uuid import UUID

from fastapi import APIRouter

from app.core.security import CurrentUserDep, GatewayDep
from app.services.gardens import as_list

router = APIRouter(tags=["community"])


@router.get("/community/content")
async def content(gateway: GatewayDep) -> dict:
    events, tips, spotlights = await asyncio.gather(
        gateway.select(
            "grower_events",
            filters={"visible": True, "status": "neq.draft"},
            order="starts_at.asc",
        ),
        gateway.select("grower_dashboard_tips", filters={"active": True}, order="priority.asc"),
        gateway.select("community_spotlights", filters={"active": True}, order="priority.asc"),
    )
    return {
        "events": as_list(events),
        "tips": as_list(tips),
        "spotlights": as_list(spotlights),
    }


@router.post("/community/events/{event_id}/registrations")
async def register_event(event_id: UUID, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    rows = await gateway.insert(
        "grower_event_registrations",
        {"event_id": str(event_id), "user_id": str(user.id), "status": "registered"},
        token=user.access_token,
        upsert=True,
        on_conflict="event_id,user_id",
    )
    return rows[0]


@router.get("/green-points")
async def green_points(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    rows = as_list(
        await gateway.select(
            "green_point_transactions",
            token=user.access_token,
            filters={"owner_id": user.id},
            order="created_at.desc",
        )
    )
    total = sum(int(row.get("points") or 0) for row in rows)
    return {"total": total, "transactions": rows}
