import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter

from app.core.errors import AppError
from app.core.security import AdminUserDep, CurrentUserDep, GatewayDep
from app.schemas.gardens import (
    CareActionCreate,
    GardenAllocationCreate,
    GardenRequestCreate,
    GardenRequestStatusUpdate,
    GardenTaskCreate,
)
from app.services.gardens import (
    allocate_garden,
    as_list,
    record_care_action,
    verify_property_access,
)

router = APIRouter(tags=["gardens"])


@router.get("/gardens/overview")
async def garden_overview(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    filters = {"owner_id": user.id}
    token = user.access_token
    (
        properties,
        installations,
        batches,
        requests,
        tasks,
        activities,
        harvests,
        stats,
    ) = await asyncio.gather(
        gateway.select("properties", token=token, filters=filters, order="created_at.desc"),
        gateway.select("installations", token=token, filters=filters, order="created_at.desc"),
        gateway.select("crop_batches", token=token, filters=filters, order="created_at.desc"),
        gateway.select("garden_requests", token=token, filters=filters, order="created_at.desc"),
        gateway.select("garden_tasks", token=token, filters=filters, order="due_at.asc"),
        gateway.select(
            "garden_activity_logs", token=token, filters=filters, order="occurred_at.desc", limit=50
        ),
        gateway.select("harvests", token=token, filters=filters, order="harvested_at.desc"),
        gateway.select("grower_stats", token=token, filters={"user_id": user.id}, single=True),
    )
    return {
        "stats": stats,
        "properties": as_list(properties),
        "installations": as_list(installations),
        "cropBatches": as_list(batches),
        "gardenRequests": as_list(requests),
        "tasks": as_list(tasks),
        "activities": as_list(activities),
        "harvests": as_list(harvests),
    }


@router.post("/garden-requests", status_code=201)
async def create_garden_request(
    payload: GardenRequestCreate, gateway: GatewayDep, user: CurrentUserDep
) -> dict:
    rows = await gateway.insert(
        "garden_requests",
        {"owner_id": str(user.id), **payload.model_dump(mode="json", exclude_none=True)},
        token=user.access_token,
    )
    return rows[0]


@router.get("/garden-requests")
async def list_garden_requests(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    filters = {} if user.has_any_role("admin", "operator") else {"owner_id": user.id}
    rows = as_list(
        await gateway.select(
            "garden_requests", token=user.access_token, filters=filters, order="created_at.desc"
        )
    )
    return {"items": rows, "count": len(rows)}


@router.patch("/garden-requests/{request_id}")
async def update_garden_request_status(
    request_id: UUID,
    payload: GardenRequestStatusUpdate,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    rows = await gateway.update(
        "garden_requests",
        {
            **payload.model_dump(exclude_none=True),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": request_id},
        token=user.access_token,
    )
    if not rows:
        raise AppError(404, "request_not_found", "Garden request not found")
    return rows[0]


@router.post("/garden-requests/{request_id}/allocation")
async def allocate_request(
    request_id: UUID,
    payload: GardenAllocationCreate,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    return await allocate_garden(gateway, request_id, payload, user)


@router.post("/gardens/{property_id}/care-actions", status_code=201)
async def create_care_action(
    property_id: UUID,
    payload: CareActionCreate,
    gateway: GatewayDep,
    user: CurrentUserDep,
) -> dict:
    return await record_care_action(gateway, property_id, payload, user)


@router.post("/garden-tasks", status_code=201)
async def create_garden_task(
    payload: GardenTaskCreate, gateway: GatewayDep, user: CurrentUserDep
) -> dict:
    property_row = await verify_property_access(gateway, payload.property_id, user)
    rows = await gateway.insert(
        "garden_tasks",
        {
            "owner_id": property_row["owner_id"],
            **payload.model_dump(mode="json", exclude_none=True),
            "status": "pending",
        },
        token=user.access_token,
    )
    return rows[0]
