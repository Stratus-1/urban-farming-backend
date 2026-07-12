import html

from fastapi import APIRouter, Request

from app.core.security import GatewayDep
from app.infrastructure.email import MailMessage
from app.schemas.communications import ContactMessageCreate, NewsletterSignup

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
    return rows[0]
