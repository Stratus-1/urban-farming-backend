import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.core.errors import AppError
from app.core.security import AdminUserDep, CurrentUserDep, GatewayDep
from app.infrastructure.postgres_gateway import PostgresGateway
from app.schemas.gardens import (
    CareActionCreate,
    GardenAllocationCreate,
    GardenInstallationComplete,
    GardenPlantingComplete,
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
from app.services.workflows import advance_workflow_stage, ready_workflow_stage

router = APIRouter(tags=["gardens"])
ALLOWED_INSTALL_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_INSTALL_PHOTO_BYTES = 12 * 1024 * 1024


@router.get("/gardens/overview")
async def garden_overview(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    filters = {"owner_id": user.id}
    token = user.access_token
    now = datetime.now(UTC)
    (
        properties,
        installations,
        batches,
        requests,
        tasks,
        activities,
        harvests,
        stats,
        collections,
        tips,
        events,
        registrations,
        spotlights,
        impact_factors,
        point_transactions,
        open_messages,
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
        gateway.select(
            "collections",
            token=token,
            filters={"owner_id": user.id, "scheduled_at": f"gte.{now.isoformat()}"},
            order="scheduled_at.asc",
            limit=5,
        ),
        gateway.select(
            "grower_dashboard_tips",
            token=token,
            filters={"active": True},
            order="priority.asc",
            limit=3,
        ),
        gateway.select(
            "grower_events",
            token=token,
            filters={
                "visible": True,
                "status": ["scheduled", "open", "full"],
                "starts_at": f"gte.{now.isoformat()}",
            },
            order="starts_at.asc",
            limit=3,
        ),
        gateway.select(
            "grower_event_registrations",
            token=token,
            filters={"user_id": user.id},
        ),
        gateway.select(
            "community_spotlights",
            token=token,
            filters={"active": True},
            order="priority.asc",
            limit=1,
        ),
        gateway.select("grower_impact_factors", token=token, filters={"active": True}),
        gateway.select("green_point_transactions", token=token, filters=filters),
        gateway.select(
            "contact_messages",
            token=token,
            filters={"user_id": user.id, "status": ["new", "open", "pending"]},
        ),
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
        "collections": as_list(collections),
        "dashboardTips": as_list(tips),
        "dashboardEvents": as_list(events),
        "eventRegistrations": as_list(registrations),
        "dashboardSpotlights": as_list(spotlights),
        "impactFactors": as_list(impact_factors),
        "greenPointTransactions": as_list(point_transactions),
        "openMessageCount": len(as_list(open_messages)),
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
    request_row = await gateway.select(
        "garden_requests", token=user.access_token, filters={"id": request_id}, single=True
    )
    if not request_row:
        raise AppError(404, "request_not_found", "Garden request not found")

    current = request_row.get("status")
    target = payload.status
    report_to_approve: dict | None = None
    if target == "inspection_scheduled" and current == "submitted":
        assignments = (
            as_list(
                await gateway.select(
                    "inspection_assignments",
                    token=user.access_token,
                    filters={
                        "garden_id": request_row.get("property_id"),
                        "status": ["pending", "in_progress"],
                    },
                    limit=1,
                )
            )
            if request_row.get("property_id")
            else []
        )
        if not assignments:
            raise AppError(
                409,
                "inspector_assignment_required",
                "Assign an inspector before scheduling the visit.",
            )
    elif target == "accepted" and current == "inspection_scheduled":
        reports = as_list(
            await gateway.select(
                "inspection_reports",
                token=user.access_token,
                filters={"garden_id": request_row.get("property_id")},
                order="submitted_at.desc",
                limit=1,
            )
        )
        report = next(
            (item for item in reports if item.get("assessment_status") == "submitted_for_approval"),
            None,
        )
        if not report:
            raise AppError(
                409,
                "inspection_report_required",
                "Wait for the inspector to submit a site assessment.",
            )
        if (
            report.get("suitability_band") == "not_suitable"
            and len((payload.admin_notes or "").strip()) < 20
        ):
            raise AppError(
                409,
                "approval_rationale_required",
                "This score is advisory. Provide a 20-character reason to approve this site.",
            )
        report_to_approve = report
    elif target == "rejected" and current in {"submitted", "inspection_scheduled"}:
        if current == "inspection_scheduled" and request_row.get("property_id"):
            reports = as_list(
                await gateway.select(
                    "inspection_reports",
                    token=user.access_token,
                    filters={"garden_id": request_row["property_id"]},
                    order="submitted_at.desc",
                    limit=1,
                )
            )
            pending_report = next(
                (
                    item
                    for item in reports
                    if item.get("assessment_status") == "submitted_for_approval"
                ),
                None,
            )
            if pending_report:
                await gateway.update(
                    "inspection_reports",
                    {"assessment_status": "rejected"},
                    filters={"id": pending_report["id"]},
                    token=user.access_token,
                )
    elif target == "needing_implements" and current == "accepted":
        pass
    elif target == "live" and current == "final_install":
        property_id = request_row.get("property_id")
        report = (
            await gateway.select(
                "inspection_reports",
                token=user.access_token,
                filters={"garden_id": property_id, "assessment_status": "approved"},
                single=True,
            )
            if property_id
            else None
        )
        installations = (
            as_list(
                await gateway.select(
                    "installations",
                    token=user.access_token,
                    filters={"property_id": property_id, "status": "active"},
                    limit=1,
                )
            )
            if property_id
            else []
        )
        batches = (
            as_list(
                await gateway.select(
                    "crop_batches",
                    token=user.access_token,
                    filters={"installation_id": installations[0]["id"]},
                )
            )
            if installations
            else []
        )
        if (
            not report
            or not installations
            or not installations[0].get("installed_at")
            or not batches
        ):
            raise AppError(
                409,
                "activation_requirements_missing",
                "Finish the approved setup and record planted crops before activation.",
            )
        if any(
            batch.get("status") != "growing" or not batch.get("planted_at") for batch in batches
        ):
            raise AppError(
                409, "planting_not_complete", "Record planting before activating the garden."
            )
        details = request_row.get("details") if isinstance(request_row.get("details"), dict) else {}
        details = {
            **details,
            "trackingState": "tracking",
            "trackingStartedAt": datetime.now(UTC).isoformat(),
            "trackingStartedBy": str(user.id),
        }
        update_payload = {
            "status": target,
            "details": details,
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
            **({"admin_notes": payload.admin_notes} if payload.admin_notes is not None else {}),
        }
        rows = await gateway.update(
            "garden_requests",
            update_payload,
            filters={"id": request_id, "status": current},
            token=user.access_token,
        )
        if not rows:
            raise AppError(
                409, "request_changed", "The request changed while activation was being recorded."
            )
        return rows[0]
    elif target == "cancelled" and current not in {"live", "rejected", "cancelled"}:
        pass
    else:
        raise AppError(
            409, "invalid_request_transition", f"Cannot move a {current} request to {target}."
        )

    rows = await gateway.update(
        "garden_requests",
        {
            **payload.model_dump(exclude_none=True),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": request_id, "status": current},
        token=user.access_token,
    )
    if not rows:
        raise AppError(
            409, "request_changed", "The request changed while this update was being recorded."
        )
    if report_to_approve:
        try:
            approved = await gateway.update(
                "inspection_reports",
                {
                    "assessment_status": "approved",
                    "notes": payload.admin_notes or report_to_approve.get("notes"),
                },
                filters={"id": report_to_approve["id"]},
                token=user.access_token,
            )
            if not approved:
                raise AppError(
                    409,
                    "assessment_approval_failed",
                    "The assessment could not be marked approved. The request status was restored.",
                )
        except Exception as error:
            await gateway.update(
                "garden_requests",
                {"status": current},
                filters={"id": request_id, "status": target},
                token=user.access_token,
            )
            if isinstance(error, AppError):
                raise
            raise AppError(
                409,
                "assessment_approval_failed",
                "The assessment could not be marked approved. The request status was restored.",
            ) from error
    if target == "inspection_scheduled":
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "property_details",
            "completed",
            evidence={
                "address": request_row.get("address"),
                "property_id": request_row.get("property_id"),
            },
        )
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "preliminary_assessment",
            "completed",
            evidence={"result": "manual_review_passed", "reviewed_by": str(user.id)},
        )
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "inspector_visit",
            "in_progress",
            evidence={"assignment_id": assignments[0]["id"]},
            next_action="Complete the site visit and submit the inspection report.",
        )
    elif target == "accepted":
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "approval",
            "completed",
            evidence={
                "decision": "approved",
                "report_id": report_to_approve["id"] if report_to_approve else None,
                "rationale": payload.admin_notes,
            },
        )
        await ready_workflow_stage(
            gateway,
            user,
            request_id,
            "installation",
            next_action="Prepare and install the approved garden infrastructure.",
        )
    elif target == "needing_implements":
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "installation",
            "in_progress",
            evidence={"work_started_by": str(user.id)},
        )
    elif target == "rejected":
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "approval",
            "rejected",
            evidence={"decision": "rejected", "rationale": payload.admin_notes},
        )
    elif target == "cancelled":
        await advance_workflow_stage(
            gateway,
            user,
            request_id,
            "approval",
            "skipped",
            evidence={"decision": "cancelled", "rationale": payload.admin_notes},
        )
    return rows[0]


@router.post("/garden-requests/{request_id}/installation/photos", status_code=201)
async def upload_installation_photo(
    request_id: UUID,
    request: Request,
    gateway: GatewayDep,
    user: AdminUserDep,
    file: UploadFile = File(...),
    label: str = Form(...),
) -> dict:
    garden_request = await gateway.select(
        "garden_requests", token=user.access_token, filters={"id": request_id}, single=True
    )
    if not garden_request or garden_request.get("status") != "needing_implements":
        raise AppError(
            409,
            "installation_not_ready",
            "Installation evidence can only be uploaded for an approved request.",
        )
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_INSTALL_PHOTO_TYPES:
        raise AppError(415, "unsupported_photo", "Use JPEG, PNG, WebP, or HEIC photos")
    content = await file.read(MAX_INSTALL_PHOTO_BYTES + 1)
    if len(content) > MAX_INSTALL_PHOTO_BYTES:
        raise AppError(413, "photo_too_large", "Installation photos must be 12 MB or smaller")
    extension = Path(file.filename or "installation.jpg").suffix.lower() or ".jpg"
    owner = str(garden_request["owner_id"])
    path = f"installations/{owner}/{request_id}/{uuid4()}{extension}"
    image_url = await request.app.state.storage.upload(
        path, content, content_type, user.access_token
    )
    return {"image_url": image_url, "label": label.strip()}


@router.post("/garden-requests/{request_id}/photos", status_code=201)
async def upload_garden_request_photo(
    request_id: UUID,
    request: Request,
    gateway: GatewayDep,
    user: CurrentUserDep,
    file: UploadFile = File(...),
    label: str = Form(...),
) -> dict:
    garden_request = await gateway.select(
        "garden_requests",
        token=user.access_token,
        filters={"id": request_id, "owner_id": user.id},
        single=True,
    )
    if not garden_request:
        raise AppError(404, "request_not_found", "Garden request not found")
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_INSTALL_PHOTO_TYPES:
        raise AppError(415, "unsupported_photo", "Use JPEG, PNG, WebP, or HEIC photos")
    content = await file.read(MAX_INSTALL_PHOTO_BYTES + 1)
    if len(content) > MAX_INSTALL_PHOTO_BYTES:
        raise AppError(413, "photo_too_large", "Garden photos must be 12 MB or smaller")
    extension = Path(file.filename or "garden.jpg").suffix.lower() or ".jpg"
    path = f"garden-requests/{user.id}/{request_id}/{uuid4()}{extension}"
    image_url = await request.app.state.storage.upload(
        path, content, content_type, user.access_token
    )
    details = (
        garden_request.get("details") if isinstance(garden_request.get("details"), dict) else {}
    )
    photos = list(details.get("photos") or [])
    photos.append({"image_url": image_url, "label": label.strip()})
    rows = await gateway.update(
        "garden_requests",
        {"details": {**details, "photos": photos}},
        filters={"id": request_id, "owner_id": user.id},
        token=user.access_token,
    )
    if not rows:
        raise AppError(409, "request_changed", "Could not link the garden photo to its request.")
    return {"photos": photos}


@router.post("/garden-requests/{request_id}/installation/complete")
async def complete_garden_installation(
    request_id: UUID,
    payload: GardenInstallationComplete,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    garden_request = await gateway.select(
        "garden_requests", token=user.access_token, filters={"id": request_id}, single=True
    )
    if not garden_request:
        raise AppError(404, "request_not_found", "Garden request not found")
    if garden_request.get("status") != "needing_implements":
        raise AppError(
            409, "installation_not_ready", "The request must be approved and awaiting installation."
        )
    if payload.installed_at > date.today():
        raise AppError(422, "invalid_install_date", "Installation date cannot be in the future.")
    if not garden_request.get("property_id"):
        raise AppError(409, "property_required", "A property must be linked before installation.")
    report = await gateway.select(
        "inspection_reports",
        token=user.access_token,
        filters={"garden_id": garden_request["property_id"], "assessment_status": "approved"},
        single=True,
    )
    if not report:
        raise AppError(
            409, "inspection_approval_required", "An approved site assessment is required."
        )
    installation_payload = {
        "install_type": payload.install_type,
        "size_m2": payload.size_m2,
        "capacity_units": payload.capacity_units,
        "installed_at": payload.installed_at.isoformat(),
        "photos": payload.photos,
        "maintenance_notes": payload.completion_notes,
    }
    if isinstance(gateway, PostgresGateway):
        updated_request, installation = await gateway.complete_garden_installation(
            request_id,
            UUID(str(garden_request["property_id"])),
            installation_payload,
            token=user.access_token,
        )
        rows = [installation]
    else:
        existing = as_list(
            await gateway.select(
                "installations",
                token=user.access_token,
                filters={"property_id": garden_request["property_id"]},
                order="created_at.asc",
                limit=1,
            )
        )
        if existing:
            rows = await gateway.update(
                "installations",
                {
                    **installation_payload,
                    "owner_id": garden_request["owner_id"],
                    "status": "active",
                },
                filters={"id": existing[0]["id"]},
                token=user.access_token,
            )
        else:
            rows = await gateway.insert(
                "installations",
                {
                    **installation_payload,
                    "owner_id": garden_request["owner_id"],
                    "property_id": garden_request["property_id"],
                    "status": "active",
                },
                token=user.access_token,
            )
        updated = await gateway.update(
            "garden_requests",
            {"status": "implements_installed"},
            filters={"id": request_id, "status": "needing_implements"},
            token=user.access_token,
        )
        if not updated:
            raise AppError(
                409,
                "request_changed",
                "The request changed while installation was being recorded. Refresh and try again.",
            )
        updated_request = updated[0]
    await advance_workflow_stage(
        gateway,
        user,
        request_id,
        "installation",
        "completed",
        evidence={
            "installation_id": rows[0]["id"],
            "installed_at": payload.installed_at.isoformat(),
            "photos": payload.photos,
        },
    )
    await ready_workflow_stage(
        gateway,
        user,
        request_id,
        "crop_allocation",
        next_action="Allocate approved crops to the installed garden.",
    )
    return {"request": updated_request, "installation": rows[0]}


@router.post("/garden-requests/{request_id}/planting/complete")
async def complete_garden_planting(
    request_id: UUID,
    payload: GardenPlantingComplete,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    garden_request = await gateway.select(
        "garden_requests", token=user.access_token, filters={"id": request_id}, single=True
    )
    if not garden_request or garden_request.get("status") != "seeds":
        raise AppError(409, "allocation_required", "Allocate crops before recording planting.")
    if payload.planted_at > date.today():
        raise AppError(422, "invalid_planting_date", "Planting date cannot be in the future.")
    installations = as_list(
        await gateway.select(
            "installations",
            token=user.access_token,
            filters={"property_id": garden_request.get("property_id"), "status": "active"},
            limit=1,
        )
    )
    if not installations or not installations[0].get("installed_at"):
        raise AppError(
            409, "installation_not_complete", "A completed physical installation is required."
        )
    batches = as_list(
        await gateway.select(
            "crop_batches",
            token=user.access_token,
            filters={"installation_id": installations[0]["id"]},
        )
    )
    if not batches:
        raise AppError(
            409, "crop_allocation_required", "Allocate at least one crop before planting."
        )
    planted_at = payload.planted_at.isoformat()
    for batch in batches:
        await gateway.update(
            "crop_batches",
            {"status": "growing", "planted_at": planted_at},
            filters={"id": batch["id"]},
            token=user.access_token,
        )
    rows = await gateway.update(
        "garden_requests",
        {"status": "final_install"},
        filters={"id": request_id, "status": "seeds"},
        token=user.access_token,
    )
    if not rows:
        raise AppError(
            409, "request_changed", "The request changed while planting was being recorded."
        )
    await advance_workflow_stage(
        gateway,
        user,
        request_id,
        "maintenance_tasks",
        "in_progress",
        evidence={"planted_at": planted_at, "crop_batch_ids": [batch["id"] for batch in batches]},
    )
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
