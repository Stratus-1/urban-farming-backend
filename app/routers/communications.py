import html
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.core.security import AdminUserDep, GatewayDep
from app.infrastructure.email import MailMessage
from app.schemas.communications import (
    AssessmentLeadConvert,
    AssessmentLeadCreate,
    AssessmentLeadStatusUpdate,
    ContactMessageCreate,
    GardenRequestNotification,
    NewsletterSignup,
    SignupNotification,
)
from app.services.mobile_push import send_push_to_audience

router = APIRouter(tags=["communications"])


@router.post("/contact", status_code=201)
async def contact(payload: ContactMessageCreate, request: Request, gateway: GatewayDep) -> dict:
    rows = await gateway.insert("contact_messages", payload.model_dump(mode="json"), token=None)
    settings = request.app.state.settings
    email = request.app.state.email
    await email.send(
        MailMessage(
            to=settings.admin_email,
            reply_to=str(payload.email),
            subject=f"Urban Farming contact: {payload.subject}",
            text=(
                f"From: {payload.name} <{payload.email}>\n"
                f"Category: {payload.category}\n\n{payload.message}"
            ),
            html=(
                f"<p><strong>From:</strong> {html.escape(payload.name)} "
                f"&lt;{html.escape(str(payload.email))}&gt;</p>"
                f"<p><strong>Category:</strong> {html.escape(payload.category)}</p>"
                f"<p>{html.escape(payload.message).replace(chr(10), '<br>')}</p>"
            ),
        )
    )
    return rows[0]


@router.put("/newsletter")
async def newsletter(payload: NewsletterSignup, gateway: GatewayDep) -> dict:
    rows = await gateway.insert(
        "newsletter_subscriptions",
        {**payload.model_dump(mode="json"), "subscribed": True},
        upsert=True,
        on_conflict="email",
    )
    # Confirmation delivery is intentionally non-transactional. The subscription remains saved
    # if an email provider is temporarily unavailable.
    return rows[0]


@router.post("/assessment-leads", status_code=201)
async def create_assessment_lead(
    payload: AssessmentLeadCreate, request: Request, gateway: GatewayDep
) -> dict:
    lead_payload = payload.model_dump(mode="json", exclude_none=True)
    rows = await gateway.insert("assessment_leads", lead_payload, token=None, admin=True)
    lead = rows[0]

    try:
        settings = request.app.state.settings
        email_gateway = request.app.state.email
        await email_gateway.send(
            MailMessage(
                to=settings.admin_email,
                reply_to=str(payload.email),
                subject=f"New assessment lead: {payload.suburb}",
                text=(
                    f"Lead ID: {lead['id']}\n"
                    f"Name: {payload.full_name}\n"
                    f"Email: {payload.email}\n"
                    f"Phone: {payload.phone or 'Not provided'}\n"
                    f"Suburb: {payload.suburb}\n"
                    f"City: {payload.city or 'Not provided'}\n"
                    f"Space type: {payload.space_type}\n"
                    f"Available space m2: {payload.available_space_m2 or 'Not provided'}\n"
                    f"Sunlight hours: {payload.sunlight_hours or 'Not provided'}\n"
                    f"Water access: {payload.water_access}\n"
                    f"Interest: {payload.interest_type}\n\n"
                    f"{payload.message or ''}"
                ),
            )
        )
    except Exception:
        pass
    return lead


@router.get("/admin/assessment-leads")
async def list_assessment_leads(gateway: GatewayDep, user: AdminUserDep) -> dict:
    rows = await gateway.select(
        "assessment_leads",
        token=user.access_token,
        admin=True,
        order="created_at.desc",
        limit=100,
    )
    items = rows if isinstance(rows, list) else []
    return {"items": items, "count": len(items)}


@router.patch("/admin/assessment-leads/{lead_id}")
async def update_assessment_lead(
    lead_id: UUID,
    payload: AssessmentLeadStatusUpdate,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    rows = await gateway.update(
        "assessment_leads",
        {
            **payload.model_dump(mode="json", exclude_none=True),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": lead_id},
        token=user.access_token,
        admin=True,
    )
    if not rows:
        raise AppError(404, "assessment_lead_not_found", "Assessment lead not found")
    return rows[0]


@router.post("/admin/assessment-leads/{lead_id}/convert", status_code=201)
async def convert_assessment_lead(
    lead_id: UUID,
    payload: AssessmentLeadConvert,
    request: Request,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    lead = await gateway.select(
        "assessment_leads",
        filters={"id": lead_id},
        token=user.access_token,
        admin=True,
        single=True,
    )
    if not lead:
        raise AppError(404, "assessment_lead_not_found", "Assessment lead not found")
    if lead.get("status") == "converted":
        raise AppError(
            409,
            "assessment_lead_already_converted",
            "Assessment lead has already been converted",
        )

    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is None:
        raise AppError(
            501,
            "native_auth_required",
            "Assessment conversion requires native GCP authentication",
        )

    existing_user = await auth_store.get_user_by_email(str(lead["email"]))
    created_user = existing_user is None
    grower_user = existing_user
    if grower_user is None:
        grower_user = await auth_store.create_user(
            email=str(lead["email"]),
            password_hash=None,
            user_metadata={
                "full_name": lead.get("full_name"),
                "phone": lead.get("phone"),
                "source": "assessment_lead",
                "assessment_lead_id": str(lead_id),
            },
            app_metadata={"provider": "assessment_lead"},
        )

    await auth_store.ensure_provisioned(
        UUID(str(grower_user["id"])),
        full_name=str(lead.get("full_name") or ""),
        role="grower",
    )

    status = "submitted"
    city = payload.city or lead.get("city")
    label = payload.label or _default_garden_request_label(lead)
    details = {
        "source": "assessment_lead_conversion",
        "assessment_lead_id": str(lead_id),
        "lead_source": lead.get("source"),
        "lead_status_before_conversion": lead.get("status"),
        "full_name": lead.get("full_name"),
        "email": lead.get("email"),
        "phone": lead.get("phone"),
        "suburb": lead.get("suburb"),
        "space_type": lead.get("space_type"),
        "water_access": lead.get("water_access"),
        "interest_type": lead.get("interest_type"),
        "lead_message": lead.get("message"),
        "converted_by": str(user.id),
        "converted_at": datetime.now(UTC).isoformat(),
    }
    request_rows = await gateway.insert(
        "garden_requests",
        {
            "owner_id": str(grower_user["id"]),
            "label": label,
            "city": city,
            "address": payload.address,
            "available_space_m2": lead.get("available_space_m2"),
            "sunlight_hours": lead.get("sunlight_hours"),
            "details": details,
            "status": status,
            "admin_notes": payload.admin_notes or lead.get("admin_notes"),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        token=user.access_token,
        admin=True,
    )
    garden_request = request_rows[0]

    update_rows = await gateway.update(
        "assessment_leads",
        {
            "status": "converted",
            "admin_notes": payload.admin_notes or lead.get("admin_notes"),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": lead_id},
        token=user.access_token,
        admin=True,
    )
    updated_lead = update_rows[0] if update_rows else lead

    return {
        "lead": updated_lead,
        "gardenRequest": garden_request,
        "userId": str(grower_user["id"]),
        "createdUser": created_user,
    }


def _default_garden_request_label(lead: dict) -> str:
    suburb = str(lead.get("suburb") or "Assessment").strip()
    space_type = str(lead.get("space_type") or "garden").replace("_", " ")
    return f"{suburb} {space_type} assessment"[:120]


@router.post("/notifications/garden-request")
async def garden_request_notification(
    payload: GardenRequestNotification, request: Request, gateway: GatewayDep
) -> dict:
    email_gateway = request.app.state.email
    settings = request.app.state.settings
    plants = ", ".join(payload.plants) if payload.plants else "Not provided"
    coordinates = (
        f"{payload.lat:.6f}, {payload.lng:.6f}"
        if payload.lat is not None and payload.lng is not None
        else "Not provided"
    )
    summary = (
        f"Request ID: {payload.request_id}\nGarden: {payload.garden_name}\n"
        f"Requester: {payload.full_name or 'Not provided'} <{payload.email}>\n"
        f"Address: {payload.address or 'Not provided'}\nCity: {payload.city or 'Not provided'}\n"
        f"Coordinates: {coordinates}\nType: {payload.garden_type or 'Not provided'}\n"
        f"Plants: {plants}"
    )
    await email_gateway.send(
        MailMessage(
            to=settings.admin_email,
            reply_to=str(payload.email),
            subject=f"New garden request: {payload.garden_name}",
            text=summary,
        )
    )
    await email_gateway.send(
        MailMessage(
            to=str(payload.email),
            subject=f"We received your garden request for {payload.garden_name}",
            text=(
                f"Hi {payload.full_name or 'there'},\n\n"
                f"We received your request for {payload.garden_name}. "
                "Our team will inspect the site and follow up before anything goes live."
            ),
        )
    )
    try:
        await send_push_to_audience(
            settings=settings,
            gateway=gateway,
            token="development",
            title="New garden request",
            body=f"{payload.garden_name} is ready for review.",
            roles=["admin", "operator"],
            data={"type": "garden_request", "request_id": payload.request_id},
        )
    except Exception:
        pass
    return {"ok": True}


@router.post("/notifications/signup")
async def signup_notification(
    payload: SignupNotification, request: Request, gateway: GatewayDep
) -> dict:
    await request.app.state.email.send(
        MailMessage(
            to=request.app.state.settings.admin_email,
            reply_to=str(payload.email),
            subject=f"New Urban Farming signup: {payload.full_name or payload.email}",
            text=(
                f"Name: {payload.full_name or 'Not provided'}\n"
                f"Email: {payload.email}\nRole: {payload.role or 'grower'}"
            ),
        )
    )
    try:
        await send_push_to_audience(
            settings=request.app.state.settings,
            gateway=gateway,
            token="development",
            title="New signup",
            body=f"{payload.full_name or payload.email} joined the platform.",
            roles=["admin", "operator"],
            data={"type": "signup", "role": payload.role or "grower"},
        )
    except Exception:
        pass
    return {"ok": True}
