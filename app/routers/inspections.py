from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.core.errors import AppError
from app.core.security import GatewayDep, InspectorUserDep
from app.schemas.inspections import ChecklistItemUpsert, InspectionStart, InspectionSubmit
from app.services.gardens import as_list

router = APIRouter(prefix="/inspections", tags=["inspections"])
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_PHOTO_BYTES = 12 * 1024 * 1024


async def inspector_record(gateway: GatewayDep, user: InspectorUserDep) -> dict:
    row = await gateway.select(
        "inspectors",
        token=user.access_token,
        filters={"user_id": user.id},
        single=True,
    )
    if not row and not user.has_any_role("admin", "operator"):
        raise AppError(403, "inspector_profile_missing", "Inspector profile not found")
    return row or {}


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
    payload: InspectionStart, gateway: GatewayDep, user: InspectorUserDep
) -> dict:
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
) -> dict:
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
) -> dict:
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError(415, "unsupported_photo", "Use JPEG, PNG, WebP, or HEIC photos")
    content = await file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise AppError(413, "photo_too_large", "Inspection photos must be 12 MB or smaller")
    extension = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    path = f"{user.id}/{report_id}/{uuid4()}{extension}"
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
    payload: InspectionSubmit, gateway: GatewayDep, user: InspectorUserDep
) -> dict:
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
