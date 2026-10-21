import hashlib
import hmac
import html
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.core.errors import AppError
from app.core.security import AdminUserDep, GatewayDep
from app.core.tokens import mint_recovery_token
from app.core.workload_identity import WorkloadIdentityError, verify_workload_identity
from app.infrastructure.email import MailMessage
from app.infrastructure.postgres_gateway import PostgresGateway
from app.schemas.communications import (
    AssessmentLeadConvert,
    AssessmentLeadCreate,
    AssessmentLeadStatusUpdate,
    ContactMessageCreate,
    GardenRequestNotification,
    HelpCenterGardenRequestCase,
    HelpCenterGardenRequestSnapshot,
    InspectorApplicationCreate,
    NewsletterSignup,
    SignupNotification,
)
from app.services.mobile_push import send_push_to_audience

router = APIRouter(tags=["communications"])
logger = structlog.get_logger(__name__)


def _support_reference(secret: str, purpose: str, value: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"urban_farming\0{purpose}\0{value}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"ufc-{digest[:28]}" if purpose == "case" else f"uf-{purpose}-{digest}"


GARDEN_REQUEST_PROJECTION_STATUSES = frozenset(
    {
        "submitted",
        "inspection_scheduled",
        "accepted",
        "needing_implements",
        "implements_installed",
        "seeds",
        "final_install",
        "live",
        "rejected",
        "cancelled",
    }
)


def project_garden_request_for_help_center(row: dict, secret: str) -> HelpCenterGardenRequestCase:
    """Project only approved lifecycle fields; requester identity remains product-owned."""
    owner_id = row.get("owner_id")
    status = str(row.get("status") or "")
    if not owner_id or status not in GARDEN_REQUEST_PROJECTION_STATUSES:
        raise ValueError("Garden request is outside the support projection contract")
    return HelpCenterGardenRequestCase(
        case_ref=_support_reference(secret, "case", str(row["id"])),
        tenant_scope_ref=_support_reference(secret, "tenant", str(owner_id)),
        requester_ref=_support_reference(secret, "user", str(owner_id)),
        category="garden_request",
        status=status,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/contact", status_code=201)
async def contact(payload: ContactMessageCreate, request: Request, gateway: GatewayDep) -> dict:
    rows = await gateway.insert("contact_messages", payload.model_dump(mode="json"), token=None)
    settings = request.app.state.settings
    email = request.app.state.email
    try:
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
    except Exception:
        logger.exception("contact_notification_failed", contact_id=str(rows[0].get("id")))
    return rows[0]


@router.get(
    "/integrations/help-center/garden-requests",
    response_model=HelpCenterGardenRequestSnapshot,
    include_in_schema=True,
)
async def help_center_garden_request_snapshot(
    request: Request,
    gateway: GatewayDep,
    authorization: str | None = Header(default=None),
    limit: int = Query(default=500, ge=1, le=500),
    tenant_scope_refs: list[str] = Header(
        alias="X-Help-Center-Tenant-Scope", min_length=1, max_length=100
    ),
) -> HelpCenterGardenRequestSnapshot:
    """Return a read-only, PII-minimized snapshot for one allowlisted service identity."""
    settings = request.app.state.settings
    if not settings.help_center_projection_enabled:
        raise HTTPException(status_code=404, detail="Support projection is unavailable")
    if settings.data_backend != "postgres" or settings.auth_mode != "native":
        raise HTTPException(
            status_code=503,
            detail="Support projection requires production data mode",
        )

    secret = settings.support_reference_secret
    audience = settings.help_center_projection_audience
    service_email = settings.help_center_service_account_email
    secret_value = secret.get_secret_value() if secret else ""
    if len(secret_value) < 32 or not audience or not service_email:
        raise HTTPException(status_code=503, detail="Support projection identity is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="A service identity token is required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        await verify_workload_identity(
            token,
            audience=audience,
            service_account_email=service_email,
        )
    except WorkloadIdentityError as error:
        raise HTTPException(status_code=401, detail="Service identity is not allowed") from error

    if any(
        not isinstance(scope, str)
        or not scope.startswith("uf-tenant-")
        or len(scope) != len("uf-tenant-") + 64
        or any(char not in "0123456789abcdef" for char in scope.removeprefix("uf-tenant-"))
        for scope in tenant_scope_refs
    ):
        raise HTTPException(status_code=422, detail="Tenant scope reference is invalid")

    rows = await gateway.select_garden_requests_for_help_center(tenant_scope_refs, limit=limit + 1)
    if len(rows) > limit:
        raise HTTPException(
            status_code=503,
            detail=(
                "Support projection exceeds the bounded snapshot size; no partial snapshot returned"
            ),
        )

    try:
        requested_scopes = set(tenant_scope_refs)
        cases = []
        for row in rows:
            projection = project_garden_request_for_help_center(row, secret_value)
            if projection.tenant_scope_ref not in requested_scopes:
                raise ValueError("Source tenant mapping does not match the configured reference")
            cases.append(projection)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Support projection source is invalid",
        ) from error

    return HelpCenterGardenRequestSnapshot(items=cases, snapshot_at=datetime.now(UTC))


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
                    f"Available space m2: {payload.available_space_m2:g}\n"
                    f"Sunlight hours: {payload.sunlight_hours or 'Not provided'}\n"
                    f"Water access: {payload.water_access}\n"
                    f"Interest: {payload.interest_type}\n\n"
                    f"{payload.message or ''}"
                ),
            )
        )
    except Exception:
        logger.exception("assessment_lead_notification_failed", lead_id=str(lead.get("id")))
    return lead


@router.post("/inspector-applications", status_code=201)
async def create_inspector_application(
    payload: InspectorApplicationCreate, request: Request, gateway: GatewayDep
) -> dict:
    option_rows = await gateway.select(
        "inspector_application_options", token=None, filters={"active": True}
    )
    valid_options = {
        (row["category"], row["value"])
        for row in (option_rows if isinstance(option_rows, list) else [])
    }
    if ("availability", payload.availability) not in valid_options:
        raise AppError(422, "invalid_application_option", "Availability option is invalid")
    if ("transport_access", payload.transport_access) not in valid_options:
        raise AppError(422, "invalid_application_option", "Transport option is invalid")
    for category, values, message in (
        ("growing_system", payload.growing_systems, "Growing system option is invalid"),
        ("inspection_experience", payload.inspection_experience, "Inspection experience option is invalid"),
        ("crop_site_knowledge", payload.crop_and_site_knowledge, "Crop and site knowledge option is invalid"),
    ):
        if any((category, value) not in valid_options for value in values):
            raise AppError(422, "invalid_application_option", message)
    application = await gateway.insert(
        "inspector_applications",
        payload.model_dump(mode="json", exclude_none=True),
        token=None,
        admin=True,
    )
    result = application[0]
    try:
        await request.app.state.email.send(
            MailMessage(
                to=request.app.state.settings.admin_email,
                reply_to=str(payload.email),
                subject=f"New inspector application: {payload.full_name}",
                text=(
                    f"Applicant: {payload.full_name}\nEmail: {payload.email}\n"
                    f"Location: {payload.city}, {payload.region}\n"
                    f"Current role: {payload.current_role}\n"
                    f"Growing experience: {payload.years_growing_experience} years\n\n"
                    f"Motivation:\n{payload.motivation}"
                ),
            )
        )
    except Exception:
        logger.exception("inspector_application_notification_failed", application_id=str(result.get("id")))
    return result


@router.get("/inspector-application-options")
async def list_inspector_application_options(gateway: GatewayDep) -> dict:
    rows = await gateway.select(
        "inspector_application_options",
        token=None,
        filters={"active": True},
        order="category.asc,sort_order.asc,label.asc",
    )
    items = rows if isinstance(rows, list) else []
    return {"items": items, "count": len(items)}


@router.get("/admin/inspector-applications")
async def list_inspector_applications(gateway: GatewayDep, user: AdminUserDep) -> dict:
    rows = await gateway.select(
        "inspector_applications",
        token=user.access_token,
        admin=True,
        order="created_at.desc",
        limit=100,
    )
    items = rows if isinstance(rows, list) else []
    return {"items": items, "count": len(items)}


@router.patch("/admin/inspector-applications/{application_id}")
async def update_inspector_application(
    application_id: UUID,
    payload: dict,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    allowed_statuses = {"pending", "under_review", "approved", "rejected"}
    status = payload.get("status")
    if status not in allowed_statuses:
        raise AppError(422, "invalid_application_status", "Inspector application status is invalid")
    rows = await gateway.update(
        "inspector_applications",
        {
            "status": status,
            "admin_notes": payload.get("admin_notes"),
            "reviewed_by": str(user.id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": application_id},
        token=user.access_token,
        admin=True,
    )
    if not rows:
        raise AppError(404, "inspector_application_not_found", "Inspector application not found")
    return rows[0]


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
    response: Response,
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
    if lead.get("status") == "converted" and not isinstance(gateway, PostgresGateway):
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
    admin_notes = payload.admin_notes or lead.get("admin_notes")
    request_values = {
        "owner_id": str(grower_user["id"]),
        "label": label,
        "city": city,
        "address": payload.address,
        "available_space_m2": lead.get("available_space_m2"),
        "sunlight_hours": lead.get("sunlight_hours"),
        "details": details,
        "status": status,
        "admin_notes": admin_notes,
        "reviewed_by": str(user.id),
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    if isinstance(gateway, PostgresGateway):
        conversion = await gateway.convert_assessment_lead(
            lead_id,
            request_values,
            user.id,
            token=user.access_token,
        )
        garden_request = conversion["garden_request"]
        updated_lead = conversion["lead"]
        request_created = conversion["created"]
        response.status_code = 201 if request_created else 200
    else:
        request_rows = await gateway.insert(
            "garden_requests",
            request_values,
            token=user.access_token,
            admin=True,
        )
        garden_request = request_rows[0]
        request_created = True
        update_rows = await gateway.update(
            "assessment_leads",
            {
                "status": "converted",
                "admin_notes": admin_notes,
                "reviewed_by": str(user.id),
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
            filters={"id": lead_id},
            token=user.access_token,
            admin=True,
        )
        if not update_rows:
            raise AppError(
                409,
                "assessment_lead_conversion_incomplete",
                "The lead conversion could not be completed. Try again.",
            )
        updated_lead = update_rows[0]

    password_setup_email_sent = False
    if created_user:
        settings = request.app.state.settings
        app_url = settings.app_base_url.rstrip("/")
        app_origin = f"{urlsplit(app_url).scheme}://{urlsplit(app_url).netloc}"
        if app_origin in settings.allowed_origins:
            token = mint_recovery_token(
                settings, UUID(str(grower_user["id"])), grower_user.get("email")
            )
            recovery_url = f"{app_url}/auth?token={quote(token, safe='')}&type=recovery"
            try:
                await request.app.state.email.send(
                    MailMessage(
                        to=str(lead["email"]),
                        subject="Finish setting up your Urban Farming account",
                        text=(
                            f"Hi {lead.get('full_name') or 'there'},\n\n"
                            "We have opened a grower account so you can follow the garden "
                            "assessment request you submitted. Set your password using the "
                            "secure link below. It expires in 30 minutes.\n\n"
                            f"{recovery_url}\n\n"
                            "If you did not submit an assessment request, you can ignore "
                            "this email."
                        ),
                    )
                )
                password_setup_email_sent = True
            except Exception:
                logger.exception(
                    "Could not send password setup email for converted assessment lead",
                    lead_id=str(lead_id),
                )
        else:
            logger.error(
                "Password setup email skipped because APP_BASE_URL is not an allowed origin",
                lead_id=str(lead_id),
            )

    return {
        "lead": updated_lead,
        "gardenRequest": garden_request,
        "gardenRequestCreated": request_created,
        "userId": str(grower_user["id"]),
        "createdUser": created_user,
        "passwordSetupEmailSent": password_setup_email_sent,
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
