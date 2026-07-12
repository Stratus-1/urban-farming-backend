import html

from fastapi import APIRouter, Request

from app.core.security import GatewayDep
from app.infrastructure.email import MailMessage
from app.schemas.communications import (
    ContactMessageCreate,
    GardenRequestNotification,
    NewsletterSignup,
    SignupNotification,
)

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


@router.post("/notifications/garden-request")
async def garden_request_notification(payload: GardenRequestNotification, request: Request) -> dict:
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
    return {"ok": True}


@router.post("/notifications/signup")
async def signup_notification(payload: SignupNotification, request: Request) -> dict:
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
    return {"ok": True}
