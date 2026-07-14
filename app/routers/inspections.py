from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from pydantic import BaseModel

from app.core.errors import AppError
from app.core.security import GatewayDep, InspectorUserDep
from app.schemas.inspections import (
    ChecklistItemUpsert,
    InspectionAssessment,
    InspectionStart,
    InspectionSubmit,
)
from app.services.gardens import as_list
from app.services.inspection_scoring import score_assessment

router = APIRouter(prefix="/inspections", tags=["inspections"])
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_PHOTO_BYTES = 12 * 1024 * 1024
PREVIEW_INSPECTOR_HEADER = "X-Inspector-Id"
CHECKLIST_TEMPLATE = (
    ("Garden condition", "Full garden view", True, 1),
    ("Crop health", "Leaf and growth check", True, 2),
    ("Irrigation status", "Watering and delivery system", True, 3),
    ("Pest and disease", "Signs of pests or disease", True, 4),
    ("Soil and beds", "Bed structure and soil condition", False, 5),
    ("Safety and access", "Safe access and working area", False, 6),
    ("User compliance", "Site usage and access checks", False, 7),
    ("Yield progress", "Expected progress and maturity", False, 8),
)


class InspectionDraft(BaseModel):
    notes: str | None = None


async def inspector_record(
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = None,
    *,
    require_preview: bool = False,
) -> dict:
    if preview_inspector_id is not None:
        if not user.has_any_role("admin", "operator"):
            raise AppError(403, "inspector_preview_forbidden", "Only admins can preview inspectors")
        row = await gateway.select(
            "inspectors",
            token=user.access_token,
            filters={"id": str(preview_inspector_id), "status": "active"},
            single=True,
        )
        if not row:
            raise AppError(404, "inspector_not_found", "Active inspector not found")
        return row

    row = await gateway.select(
        "inspectors",
        token=user.access_token,
        filters={"user_id": user.id},
        single=True,
    )
    if row:
        return row
    if user.has_any_role("admin", "operator"):
        if require_preview:
            raise AppError(
                400,
                "inspector_preview_required",
                "Select an inspector to preview this action",
            )
        return {}
    raise AppError(403, "inspector_profile_missing", "Inspector profile not found")


async def ensure_assignment_access(
    assignment_id: UUID,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = None,
) -> tuple[dict, dict]:
    assignment = await gateway.select(
        "inspection_assignments",
        token=user.access_token,
        filters={"id": str(assignment_id)},
        single=True,
    )
    if not assignment:
        raise AppError(404, "inspection_assignment_not_found", "Inspection assignment not found")
    inspector = await inspector_record(
        gateway,
        user,
        preview_inspector_id,
        require_preview=user.has_any_role("admin", "operator"),
    )
    if str(assignment.get("inspector_id")) != str(inspector.get("id")):
        raise AppError(
            403,
            "inspection_assignment_forbidden",
            "This assignment is not assigned to you",
        )
    return assignment, inspector


async def ensure_report_access(
    report_id: UUID,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = None,
) -> tuple[dict, dict]:
    report = await gateway.select(
        "inspection_reports",
        token=user.access_token,
        filters={"id": str(report_id)},
        single=True,
    )
    if not report:
        raise AppError(404, "inspection_report_not_found", "Inspection report not found")
    inspector = await inspector_record(
        gateway,
        user,
        preview_inspector_id,
        require_preview=user.has_any_role("admin", "operator"),
    )
    if str(report.get("inspector_id")) != str(inspector.get("id")):
        raise AppError(403, "inspection_report_forbidden", "This report is not assigned to you")
    return report, inspector


def seed_checklist_items(report_id: str) -> list[dict]:
    return [
        {
            "report_id": report_id,
            "category": category,
            "item_name": item_name,
            "result": "na",
            "comment": None,
            "requires_photo": requires_photo,
            "sort_order": sort_order,
        }
        for category, item_name, requires_photo, sort_order in CHECKLIST_TEMPLATE
    ]


@router.get("/dashboard")
async def inspector_dashboard(
    gateway: GatewayDep,
    user: InspectorUserDep,
    inspector_id: UUID | None = Query(default=None),
) -> dict:
    inspector = await inspector_record(
        gateway,
        user,
        inspector_id,
        require_preview=user.has_any_role("admin", "operator") and inspector_id is None,
    )
    token = user.access_token
    assignments = as_list(await gateway.select(
        "inspection_assignments", token=token, filters={"inspector_id": inspector["id"]},
        order="due_date.asc",
    ))
    garden_ids = list({row["garden_id"] for row in assignments if row.get("garden_id")})
    reports = as_list(await gateway.select(
        "inspection_reports", token=token, filters={"inspector_id": inspector["id"]},
        order="updated_at.desc",
    ))
    report_ids = list({row["id"] for row in reports if row.get("id")})
    properties = as_list(await gateway.select(
        "properties", token=token, filters={"id": garden_ids},
    )) if garden_ids else []
    owner_ids = list({row["owner_id"] for row in properties if row.get("owner_id")})
    installations = as_list(await gateway.select(
        "installations", token=token, filters={"property_id": garden_ids},
        order="created_at.desc",
    )) if garden_ids else []
    profiles = as_list(await gateway.select(
        "profiles", token=token, filters={"id": owner_ids},
    )) if owner_ids else []
    checklist_items = as_list(await gateway.select(
        "inspection_checklist_items", token=token, filters={"report_id": report_ids},
        order="sort_order.asc",
    )) if report_ids else []
    photos = as_list(await gateway.select(
        "inspection_photos", token=token, filters={"report_id": report_ids},
        order="created_at.asc",
    )) if report_ids else []
    return {
        "inspector": inspector, "assignments": assignments, "properties": properties,
        "ownerProfiles": profiles, "installations": installations, "reports": reports,
        "checklistItems": checklist_items, "photos": photos,
    }


@router.get("/assignments")
async def assignments(gateway: GatewayDep, user: InspectorUserDep) -> dict:
    inspector = await inspector_record(gateway, user)
    filters = {} if user.has_any_role("admin", "operator") else {"inspector_id": inspector["id"]}
    rows = as_list(
        await gateway.select(
            "inspection_assignments",
            token=user.access_token,
            filters=filters,
            order="scheduled_for.asc",
        )
    )
    return {"items": rows, "count": len(rows)}


@router.post("/reports/start")
async def start_report(
    payload: InspectionStart,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    if preview_inspector_id is not None or (
        user.has_any_role("admin", "operator") and not user.has_any_role("inspector")
    ):
        assignment, inspector = await ensure_assignment_access(
            payload.assignment_id,
            gateway,
            user,
            preview_inspector_id,
        )
        existing_report = await gateway.select(
            "inspection_reports",
            token=user.access_token,
            filters={"assignment_id": str(payload.assignment_id)},
            single=True,
        )
        if existing_report:
            return {"report": [existing_report]}
        started_at = datetime.now(UTC).isoformat()
        report_rows = await gateway.insert(
            "inspection_reports",
            {
                "assignment_id": str(payload.assignment_id),
                "inspector_id": str(inspector["id"]),
                "garden_id": str(assignment["garden_id"]),
                "overall_status": "pending",
                "notes": None,
                "gps_lat": payload.gps_lat,
                "gps_lng": payload.gps_lng,
                "started_at": started_at,
            },
            token=user.access_token,
        )
        await gateway.update(
            "inspection_assignments",
            {
                "status": "in_progress",
                "started_at": assignment.get("started_at") or started_at,
                "updated_at": started_at,
            },
            filters={"id": str(payload.assignment_id)},
            token=user.access_token,
        )
        await gateway.insert(
            "inspection_checklist_items",
            seed_checklist_items(str(report_rows[0]["id"])),
            token=user.access_token,
        )
        return {"report": report_rows}

    result = await gateway.rpc(
        "start_inspection_report",
        {
            "p_assignment_id": str(payload.assignment_id),
            "p_gps_lat": payload.gps_lat,
            "p_gps_lng": payload.gps_lng,
        },
        token=user.access_token,
    )
    return {"report": result}


@router.put("/reports/{report_id}/checklist/{checklist_item_id}")
async def upsert_checklist_item(
    report_id: UUID,
    checklist_item_id: UUID,
    payload: ChecklistItemUpsert,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    await ensure_report_access(report_id, gateway, user, preview_inspector_id)
    rows = await gateway.insert(
        "inspection_checklist_items",
        {
            "id": str(checklist_item_id),
            "report_id": str(report_id),
            **payload.model_dump(mode="json"),
        },
        token=user.access_token,
        upsert=True,
        on_conflict="id",
    )
    return rows[0]


@router.patch("/reports/{report_id}")
async def save_report_draft(
    report_id: UUID,
    payload: InspectionDraft,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    await ensure_report_access(report_id, gateway, user, preview_inspector_id)
    rows = await gateway.update(
        "inspection_reports",
        {"notes": payload.notes, "updated_at": datetime.now(UTC).isoformat()},
        filters={"id": str(report_id)}, token=user.access_token,
    )
    return rows[0]


@router.post("/reports/{report_id}/photos", status_code=201)
async def upload_photo(
    report_id: UUID,
    request: Request,
    gateway: GatewayDep,
    user: InspectorUserDep,
    file: UploadFile = File(...),
    label: str = Form(...),
    checklist_item_id: UUID | None = Form(default=None),
    photo_type: str = Form(default="extra"),
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    _, inspector = await ensure_report_access(report_id, gateway, user, preview_inspector_id)
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError(415, "unsupported_photo", "Use JPEG, PNG, WebP, or HEIC photos")
    content = await file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise AppError(413, "photo_too_large", "Inspection photos must be 12 MB or smaller")
    extension = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    path = f"{inspector['user_id']}/{report_id}/{uuid4()}{extension}"
    storage_path = await request.app.state.storage.upload(
        path, content, content_type, user.access_token
    )
    rows = await gateway.insert(
        "inspection_photos",
        {
            "report_id": str(report_id),
            "checklist_item_id": str(checklist_item_id) if checklist_item_id else None,
            "image_url": storage_path,
            "label": label,
            "photo_type": photo_type,
        },
        token=user.access_token,
    )
    return rows[0]


@router.post("/reports/submit")
async def submit_report(
    payload: InspectionSubmit,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    if preview_inspector_id is not None or (
        user.has_any_role("admin", "operator") and not user.has_any_role("inspector")
    ):
        report, _ = await ensure_report_access(
            payload.report_id,
            gateway,
            user,
            preview_inspector_id,
        )
        if payload.overall_status not in {"pass", "warning", "fail"}:
            raise AppError(422, "invalid_inspection_status", "Invalid inspection status")
        submitted_at = datetime.now(UTC).isoformat()
        rows = await gateway.update(
            "inspection_reports",
            {
                "overall_status": payload.overall_status,
                "notes": payload.notes,
                "follow_up_required": payload.follow_up_required,
                "gps_lat": payload.gps_lat,
                "gps_lng": payload.gps_lng,
                "submitted_at": submitted_at,
                "updated_at": submitted_at,
            },
            filters={"id": str(payload.report_id)},
            token=user.access_token,
        )
        assignment_status = (
            "failed"
            if payload.overall_status == "fail"
            else "flagged"
            if payload.follow_up_required
            else "completed"
        )
        await gateway.update(
            "inspection_assignments",
            {
                "status": assignment_status,
                "completed_at": submitted_at,
                "updated_at": submitted_at,
            },
            filters={"id": str(report["assignment_id"])},
            token=user.access_token,
        )
        return {"report": rows}

    result = await gateway.rpc(
        "submit_inspection_report",
        {
            "p_report_id": str(payload.report_id),
            "p_overall_status": payload.overall_status,
            "p_notes": payload.notes,
            "p_follow_up_required": payload.follow_up_required,
            "p_gps_lat": payload.gps_lat,
            "p_gps_lng": payload.gps_lng,
        },
        token=user.access_token,
    )
    return {"report": result}


@router.put("/reports/{report_id}/assessment")
async def save_assessment(
    report_id: UUID,
    payload: InspectionAssessment,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    report, _ = await ensure_report_access(report_id, gateway, user, preview_inspector_id)
    if report.get("assessment_status") == "submitted_for_approval":
        raise AppError(409, "assessment_already_submitted", "This assessment is awaiting approval")
    scored = score_assessment(payload)
    rows = await gateway.update(
        "inspection_reports",
        {
            "sunlight_hours": scored.sunlight_hours,
            "water_access": scored.water_access,
            "usable_space_m2": scored.usable_space_m2,
            "installation_types": scored.installation_types,
            "measurements": scored.measurements,
            "risks": [risk.model_dump() for risk in scored.risks],
            "suitability_score": scored.suitability_score,
            "score_breakdown": scored.score_breakdown,
            "suitability_band": scored.suitability_band,
            "recommended_crops": scored.recommended_crops,
            "recommended_infrastructure": scored.recommended_infrastructure,
            "assessment_status": "draft",
        },
        filters={"id": str(report_id)},
        token=user.access_token,
    )
    if not rows:
        raise AppError(404, "inspection_report_not_found", "Inspection report not found")
    return {"report": rows[0], "assessment": scored.model_dump()}


@router.post("/reports/{report_id}/submit-for-approval")
async def submit_for_approval(
    report_id: UUID,
    payload: InspectionAssessment,
    gateway: GatewayDep,
    user: InspectorUserDep,
    preview_inspector_id: UUID | None = Header(default=None, alias=PREVIEW_INSPECTOR_HEADER),
) -> dict:
    report, _ = await ensure_report_access(report_id, gateway, user, preview_inspector_id)
    if report.get("assessment_status") == "submitted_for_approval":
        raise AppError(
            409,
            "assessment_already_submitted",
            "This assessment is already awaiting approval",
        )
    scored = score_assessment(payload)
    if not scored.recommended_crops or not scored.recommended_infrastructure:
        raise AppError(
            422,
            "recommendations_required",
            "Add at least one crop and infrastructure recommendation before submission",
        )
    submitted_at = datetime.now(UTC).isoformat()
    overall_status = {
        "suitable": "pass",
        "conditional": "warning",
        "not_suitable": "fail",
    }[scored.suitability_band]
    rows = await gateway.update(
        "inspection_reports",
        {
            "sunlight_hours": scored.sunlight_hours,
            "water_access": scored.water_access,
            "usable_space_m2": scored.usable_space_m2,
            "installation_types": scored.installation_types,
            "measurements": scored.measurements,
            "risks": [risk.model_dump() for risk in scored.risks],
            "suitability_score": scored.suitability_score,
            "score_breakdown": scored.score_breakdown,
            "suitability_band": scored.suitability_band,
            "recommended_crops": scored.recommended_crops,
            "recommended_infrastructure": scored.recommended_infrastructure,
            "assessment_status": "submitted_for_approval",
            "overall_status": overall_status,
            "follow_up_required": scored.suitability_band != "suitable",
            "submitted_at": submitted_at,
        },
        filters={"id": str(report_id)},
        token=user.access_token,
    )
    if not rows:
        raise AppError(404, "inspection_report_not_found", "Inspection report not found")
    await gateway.update(
        "inspection_assignments",
        {"status": "completed", "completed_at": submitted_at},
        filters={"id": str(report["assignment_id"])},
        token=user.access_token,
    )
    return {"report": rows[0], "assessment": scored.model_dump()}
