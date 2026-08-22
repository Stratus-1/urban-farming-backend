from fastapi import APIRouter, Header, Request

from app.core.security import CurrentUserDep, GatewayDep
from app.schemas.billing import BillingOverview, CheckoutSessionResponse, PortalSessionResponse
from app.schemas.common import MessageResponse
from app.services.billing import (
    billing_update_from_event,
    build_billing_plans,
    create_checkout_session,
    create_portal_session,
    get_user_billing_settings,
    parse_webhook_event,
    subscription_from_settings,
    upsert_user_billing_settings,
    verify_webhook_signature,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("", response_model=BillingOverview)
async def get_billing_overview(
    request: Request,
    gateway: GatewayDep,
    user: CurrentUserDep,
) -> BillingOverview:
    settings = request.app.state.settings
    current_settings = await get_user_billing_settings(gateway, user)
    return BillingOverview(
        plans=build_billing_plans(settings),
        subscription=subscription_from_settings(current_settings),
        publishable_key=settings.stripe_publishable_key,
    )


@router.get("/subscription", response_model=BillingOverview)
async def get_subscription(
    request: Request,
    gateway: GatewayDep,
    user: CurrentUserDep,
) -> BillingOverview:
    return await get_billing_overview(request, gateway, user)


@router.post("/checkout-session", response_model=CheckoutSessionResponse)
async def post_checkout_session(
    request: Request, gateway: GatewayDep, user: CurrentUserDep
) -> CheckoutSessionResponse:
    current_settings = await get_user_billing_settings(gateway, user)
    url = await create_checkout_session(
        request.app.state.settings,
        user,
        current_settings,
        request.app.state.http,
    )
    return CheckoutSessionResponse(checkout_url=url)


@router.post("/portal-session", response_model=PortalSessionResponse)
async def post_portal_session(
    request: Request, gateway: GatewayDep, user: CurrentUserDep
) -> PortalSessionResponse:
    current_settings = await get_user_billing_settings(gateway, user)
    subscription = subscription_from_settings(current_settings)
    url = await create_portal_session(
        request.app.state.settings,
        subscription.customer_id or "",
        request.app.state.http,
    )
    return PortalSessionResponse(portal_url=url)


@router.post("/webhooks", response_model=MessageResponse)
async def post_webhook(
    request: Request,
    gateway: GatewayDep,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> MessageResponse:
    payload = await request.body()
    settings = request.app.state.settings
    verify_webhook_signature(payload, stripe_signature, settings)
    event = parse_webhook_event(payload)
    update = billing_update_from_event(event)
    if update:
        user_id, patch = update
        await upsert_user_billing_settings(gateway, user_id=user_id, payload=patch, admin=True)
    return MessageResponse(message="Webhook processed")
