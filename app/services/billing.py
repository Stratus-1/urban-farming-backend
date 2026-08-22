import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.data_gateway import DataGateway
from app.schemas.billing import BillingPlan, BillingSubscription
from app.schemas.common import CurrentUser

STRIPE_API_BASE = "https://api.stripe.com/v1"
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def build_billing_plans(settings: Settings) -> list[BillingPlan]:
    return [
        BillingPlan(
            code="premium-monthly",
            name=settings.stripe_premium_monthly_name,
            interval="month",
            amount=settings.stripe_premium_monthly_amount_zar,
            currency="zar",
            description="Premium resources, exclusive workshops, and expert support.",
            stripe_price_id=settings.stripe_price_premium_monthly,
            featured=True,
        )
    ]


def subscription_from_settings(row: dict[str, Any] | None) -> BillingSubscription:
    row = row or {}
    status = str(row.get("billing_subscription_status") or "inactive")
    current_period_end = _parse_datetime(row.get("billing_current_period_end"))
    return BillingSubscription(
        plan_code=row.get("billing_plan_code"),
        status=status,
        active=status in ACTIVE_SUBSCRIPTION_STATUSES,
        current_period_end=current_period_end,
        cancel_at_period_end=bool(row.get("billing_cancel_at_period_end") or False),
        customer_id=row.get("billing_customer_id"),
        subscription_id=row.get("billing_subscription_id"),
    )


async def get_user_billing_settings(
    gateway: DataGateway, user: CurrentUser, *, admin: bool = False
) -> dict[str, Any] | None:
    result = await gateway.select(
        "user_settings",
        token=None if admin else user.access_token,
        admin=admin,
        filters={"user_id": user.id},
        single=True,
    )
    return result if isinstance(result, dict) else None


async def upsert_user_billing_settings(
    gateway: DataGateway,
    *,
    user_id: str,
    payload: dict[str, Any],
    token: str | None = None,
    admin: bool = False,
) -> dict[str, Any]:
    rows = await gateway.insert(
        "user_settings",
        {"user_id": user_id, **payload},
        token=token,
        admin=admin,
        upsert=True,
        on_conflict="user_id",
    )
    return rows[0]


async def create_checkout_session(
    settings: Settings,
    user: CurrentUser,
    existing_settings: dict[str, Any] | None,
    client: httpx.AsyncClient,
) -> str:
    if not settings.stripe_secret_key or not settings.stripe_price_premium_monthly:
        raise AppError(503, "billing_unavailable", "Billing is not configured yet")

    form_data = {
        "mode": "subscription",
        "success_url": f"{settings.app_base_url.rstrip('/')}{settings.stripe_billing_success_path}",
        "cancel_url": f"{settings.app_base_url.rstrip('/')}{settings.stripe_billing_cancel_path}",
        "line_items[0][price]": settings.stripe_price_premium_monthly,
        "line_items[0][quantity]": "1",
        "allow_promotion_codes": "true",
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[plan_code]": "premium-monthly",
        "subscription_data[metadata][user_id]": str(user.id),
        "subscription_data[metadata][plan_code]": "premium-monthly",
    }
    customer_id = (existing_settings or {}).get("billing_customer_id")
    if customer_id:
        form_data["customer"] = customer_id
    elif user.email:
        form_data["customer_email"] = user.email

    payload = await _stripe_request(
        client,
        settings,
        "POST",
        "/checkout/sessions",
        data=form_data,
    )
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise AppError(502, "billing_error", "Checkout session could not be created")
    return url


async def create_portal_session(
    settings: Settings,
    customer_id: str,
    client: httpx.AsyncClient,
) -> str:
    if not settings.stripe_secret_key:
        raise AppError(503, "billing_unavailable", "Billing is not configured yet")
    if not customer_id:
        raise AppError(
            409,
            "billing_customer_missing",
            "No billing profile exists for this account",
        )
    payload = await _stripe_request(
        client,
        settings,
        "POST",
        "/billing_portal/sessions",
        data={
            "customer": customer_id,
            "return_url": f"{settings.app_base_url.rstrip('/')}/settings",
        },
    )
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise AppError(502, "billing_error", "Billing portal session could not be created")
    return url


def verify_webhook_signature(
    payload: bytes,
    signature_header: str | None,
    settings: Settings,
) -> None:
    if not settings.stripe_webhook_secret:
        raise AppError(503, "billing_unavailable", "Billing webhook is not configured yet")
    if not signature_header:
        raise AppError(400, "missing_signature", "Missing Stripe signature")

    values: dict[str, list[str]] = {}
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values.setdefault(key.strip(), []).append(value.strip())

    timestamp = (values.get("t") or [None])[0]
    signatures = values.get("v1") or []
    if not timestamp or not signatures:
        raise AppError(400, "invalid_signature", "Invalid Stripe signature header")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode()
    expected = hmac.new(
        settings.stripe_webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise AppError(400, "invalid_signature", "Stripe signature verification failed")


def parse_webhook_event(payload: bytes) -> dict[str, Any]:
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise AppError(400, "invalid_payload", "Invalid Stripe payload") from error


def billing_update_from_event(event: dict[str, Any]) -> tuple[str | None, dict[str, Any]] | None:
    event_type = str(event.get("type") or "")
    event_data = event.get("data")
    data = (
        (event_data.get("object") or {}) if isinstance(event_data, dict) else {}
    )
    if not isinstance(data, dict):
        return None

    if event_type == "checkout.session.completed":
        user_id = _read_user_id(data)
        if not user_id:
            return None
        return user_id, {
            "billing_plan_code": "premium-monthly",
            "billing_customer_id": data.get("customer"),
            "billing_subscription_id": data.get("subscription"),
            "billing_subscription_status": "active",
        }

    subscription_events = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
    if event_type in subscription_events:
        user_id = _read_user_id(data)
        if not user_id:
            return None
        status = str(data.get("status") or "inactive")
        current_period_end = _unix_to_iso(data.get("current_period_end"))
        return user_id, {
            "billing_plan_code": "premium-monthly",
            "billing_customer_id": data.get("customer"),
            "billing_subscription_id": data.get("id"),
            "billing_subscription_status": "canceled" if event_type.endswith("deleted") else status,
            "billing_current_period_end": current_period_end,
            "billing_cancel_at_period_end": bool(data.get("cancel_at_period_end") or False),
        }

    return None


async def _stripe_request(
    client: httpx.AsyncClient,
    settings: Settings,
    method: str,
    path: str,
    *,
    data: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = await client.request(
            method,
            f"{STRIPE_API_BASE}{path}",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
            data=data,
        )
    except httpx.HTTPError as error:
        raise AppError(502, "billing_unavailable", "Billing provider is unavailable") from error

    if response.is_error:
        if response.headers.get("content-type", "").startswith("application/json"):
            details = response.json().get("error", {})
        else:
            details = {}
        raise AppError(
            response.status_code,
            str(details.get("code") or "billing_error"),
            str(details.get("message") or "Billing request failed"),
        )
    return response.json()


def _read_user_id(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    user_id = metadata.get("user_id") or payload.get("client_reference_id")
    return str(user_id) if user_id else None


def _unix_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
