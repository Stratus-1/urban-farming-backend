from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.infrastructure.data_gateway import DataGateway
from app.schemas.common import CurrentUser
from app.schemas.gardens import CareActionCreate, GardenAllocationCreate

ACTION_COPY = {
    "watering": ("Watering recorded", "Water garden", 2),
    "feeding": ("Feeding recorded", "Feed crops", 7),
    "pruning": ("Pruning recorded", "Check for pruning", 10),
    "inspection": ("Garden inspection recorded", "Inspect garden", 3),
    "pest_check": ("Pest check recorded", "Check for pests", 4),
}


def as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return list(value)


async def verify_property_access(
    gateway: DataGateway, property_id: UUID, user: CurrentUser
) -> dict[str, Any]:
    filters: dict[str, Any] = {"id": property_id}
    if not user.has_any_role("admin", "operator"):
        filters["owner_id"] = user.id
    property_row = await gateway.select(
        "properties", token=user.access_token, filters=filters, single=True
    )
    if not property_row:
        raise AppError(404, "garden_not_found", "Garden not found")
    return property_row


async def record_care_action(
    gateway: DataGateway,
    property_id: UUID,
    payload: CareActionCreate,
    user: CurrentUser,
) -> dict[str, Any]:
    property_row = await verify_property_access(gateway, property_id, user)
    if payload.installation_id:
        installation = await gateway.select(
            "installations",
            token=user.access_token,
            filters={
                "id": payload.installation_id,
                "property_id": property_id,
                "owner_id": property_row["owner_id"],
            },
            single=True,
        )
        if not installation:
            raise AppError(404, "installation_not_found", "Garden setup not found")

    default_title, next_title, cadence_days = ACTION_COPY[payload.action_type]
    database_action_type = (
        "pest_control" if payload.action_type == "pest_check" else payload.action_type
    )
    title = (
        f"Watered {property_row.get('label') or 'garden'}"
        if payload.action_type == "watering" and payload.amount
        else default_title
    )
    details = {
        "amount": payload.amount,
        "unit": payload.unit,
        "method": payload.method,
        "cropFocus": payload.crop_focus,
        "condition": payload.condition,
        "notes": payload.notes,
        "source": "gcp_api",
    }
    inserted = await gateway.insert(
        "garden_activity_logs",
        {
            "owner_id": str(property_row["owner_id"]),
            "property_id": str(property_id),
            "installation_id": str(payload.installation_id) if payload.installation_id else None,
            "activity_type": database_action_type,
            "title": title,
            "occurred_at": payload.occurred_at.isoformat(),
            "details": details,
        },
        token=user.access_token,
    )
    activity = inserted[0]

    open_tasks = as_list(
        await gateway.select(
            "garden_tasks",
            token=user.access_token,
            columns="*",
            filters={
                "owner_id": property_row["owner_id"],
                "property_id": property_id,
                "task_type": database_action_type,
                "status": ["pending", "in_progress", "blocked"],
            },
            order="due_at.asc",
            limit=1,
        )
    )
    if open_tasks:
        await gateway.update(
            "garden_tasks",
            {
                "status": "done",
                "completed_at": payload.occurred_at.isoformat(),
                "notes": payload.notes,
                "metadata": details,
            },
            filters={"id": open_tasks[0]["id"], "owner_id": property_row["owner_id"]},
            token=user.access_token,
        )

    next_due = payload.occurred_at + timedelta(days=cadence_days)
    await gateway.insert(
        "garden_tasks",
        {
            "owner_id": str(property_row["owner_id"]),
            "property_id": str(property_id),
            "installation_id": str(payload.installation_id) if payload.installation_id else None,
            "task_type": database_action_type,
            "title": next_title,
            "status": "pending",
            "due_at": next_due.date().isoformat(),
            "notes": f"Focus: {payload.crop_focus}" if payload.crop_focus else None,
            "metadata": {
                "generatedFromActivityId": activity["id"],
                "cadenceDays": cadence_days,
                "source": "gcp_api",
            },
        },
        token=user.access_token,
    )
    return {"id": activity["id"], "title": title, "nextDueAt": next_due.date().isoformat()}


def installation_type(details: dict[str, Any]) -> str:
    value = f"{details.get('method', '')} {details.get('gardenType', '')}".lower()
    for needle, result in (
        ("greenhouse", "greenhouse"),
        ("aquapon", "aquaponic"),
        ("hydro", "hydroponic"),
        ("wicking", "wicking_bed"),
        ("vertical", "vertical_planter"),
        ("container", "container_garden"),
        ("raised", "raised_bed"),
    ):
        if needle in value:
            return result
    return "soil_bed"


async def allocate_garden(
    gateway: DataGateway,
    request_id: UUID,
    payload: GardenAllocationCreate,
    user: CurrentUser,
) -> dict[str, Any]:
    request = await gateway.select(
        "garden_requests",
        token=user.access_token,
        filters={"id": request_id},
        single=True,
    )
    if not request:
        raise AppError(404, "request_not_found", "Garden request not found")

    details = request.get("details") if isinstance(request.get("details"), dict) else {}
    allocated = list(
        dict.fromkeys(item.strip() for item in payload.allocated_plants if item.strip())
    )
    crops = as_list(
        await gateway.select(
            "crops", token=user.access_token, filters={"name": allocated}, columns="*"
        )
    )
    if not crops:
        raise AppError(422, "crops_not_found", "None of the allocated crops exist in the catalog")

    property_id = request.get("property_id")
    property_payload = {
        "owner_id": request["owner_id"],
        "label": request["label"],
        "address": request.get("address"),
        "city": request.get("city"),
        "lat": request.get("lat"),
        "lng": request.get("lng"),
        "available_space_m2": request.get("available_space_m2"),
        "sunlight_hours": request.get("sunlight_hours"),
        "notes": payload.allocation_notes or payload.inspection_notes or request.get("admin_notes"),
    }
    if property_id:
        await gateway.update(
            "properties",
            property_payload,
            filters={"id": property_id},
            token=user.access_token,
        )
    else:
        property_rows = await gateway.insert(
            "properties", property_payload, token=user.access_token
        )
        property_id = property_rows[0]["id"]

    installations = as_list(
        await gateway.select(
            "installations",
            token=user.access_token,
            filters={"property_id": property_id},
            order="created_at.asc",
            limit=1,
        )
    )
    if installations:
        installation = installations[0]
        if installation.get("status") != "active":
            await gateway.update(
                "installations",
                {"status": "active", "size_m2": request.get("available_space_m2") or 0},
                filters={"id": installation["id"]},
                token=user.access_token,
            )
    else:
        rows = await gateway.insert(
            "installations",
            {
                "owner_id": request["owner_id"],
                "property_id": property_id,
                "install_type": installation_type(details),
                "size_m2": request.get("available_space_m2") or 0,
                "capacity_units": max(12, len(allocated) * 4),
                "status": "active",
                "installed_at": date.today().isoformat(),
                "photos": [],
            },
            token=user.access_token,
        )
        installation = rows[0]

    existing_batches = as_list(
        await gateway.select(
            "crop_batches",
            token=user.access_token,
            columns="crop_id",
            filters={"installation_id": installation["id"]},
        )
    )
    existing_crop_ids = {str(row["crop_id"]) for row in existing_batches}
    batches = [
        {
            "owner_id": request["owner_id"],
            "installation_id": installation["id"],
            "crop_id": crop["id"],
            "units": 1,
            "expected_yield_kg": crop.get("est_yield_kg_per_unit") or 0,
            "status": "growing",
        }
        for crop in crops
        if str(crop["id"]) not in existing_crop_ids
    ]
    if batches:
        await gateway.insert("crop_batches", batches, token=user.access_token)

    requested_plants = details.get("requestedPlants") or details.get("plants") or []
    details.update(
        {
            "requestedPlants": requested_plants,
            "allocatedPlants": allocated,
            "inspectionNotes": payload.inspection_notes,
            "allocationNotes": payload.allocation_notes,
            "trackingState": "tracking",
            "trackingStartedAt": datetime.now(UTC).isoformat(),
            "trackingStartedBy": str(user.id),
        }
    )
    await gateway.update(
        "garden_requests",
        {
            "property_id": property_id,
            "status": "live",
            "reviewed_by": str(user.id),
            "admin_notes": payload.allocation_notes,
            "details": details,
        },
        filters={"id": request_id},
        token=user.access_token,
    )
    await gateway.insert(
        "garden_activity_logs",
        [
            {
                "owner_id": request["owner_id"],
                "property_id": property_id,
                "installation_id": installation["id"],
                "activity_type": "inspection",
                "title": "Site inspected",
                "details": {"meta": payload.inspection_notes, "points": 20},
            },
            {
                "owner_id": request["owner_id"],
                "property_id": property_id,
                "installation_id": installation["id"],
                "activity_type": "planting",
                "title": "Crops allocated",
                "details": {"allocated_plants": allocated, "points": 35},
            },
        ],
        token=user.access_token,
    )
    return {
        "ok": True,
        "requestId": str(request_id),
        "propertyId": str(property_id),
        "installationId": str(installation["id"]),
        "allocatedPlants": allocated,
        "matchedPlants": [crop["name"] for crop in crops],
    }
