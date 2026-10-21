import asyncio
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.core.errors import AppError
from app.core.security import AdminUserDep, GatewayDep
from app.email.templates import order_status_update
from app.services.gardens import as_list

router = APIRouter(prefix="/admin", tags=["admin"])
logger = structlog.get_logger(__name__)

ORDER_TRANSITIONS = {
    "draft": {"pending", "cancelled"},
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"fulfilling", "cancelled"},
    "fulfilling": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class OrderStatusUpdate(BaseModel):
    status: Literal["pending", "confirmed", "fulfilling", "shipped", "delivered", "cancelled"]


@router.get("/dashboard")
async def dashboard(
    gateway: GatewayDep,
    user: AdminUserDep,
    range_days: int = Query(default=7, ge=1, le=365),
) -> dict:
    token = user.access_token
    (
        summary,
        overview,
        order_status,
        top_crops,
        recent_orders,
        recent_messages,
        trends,
    ) = await asyncio.gather(
        gateway.rpc("admin_dashboard_summary", {}, token=token),
        gateway.rpc("admin_dashboard_overview", {"range_days": range_days}, token=token),
        gateway.rpc("admin_dashboard_order_status", {}, token=token),
        gateway.rpc("admin_dashboard_top_crops", {"limit_count": 5}, token=token),
        gateway.rpc("admin_dashboard_recent_orders", {"limit_count": 5}, token=token),
        gateway.rpc("admin_dashboard_recent_messages", {"limit_count": 4}, token=token),
        gateway.rpc("admin_dashboard_trends", {"range_days": range_days}, token=token),
    )
    return {
        "summary": summary,
        "overview": overview,
        "orderStatus": order_status,
        "topCrops": top_crops,
        "recentOrders": recent_orders,
        "recentMessages": recent_messages,
        "trends": trends,
    }


@router.get("/users")
async def users(gateway: GatewayDep, user: AdminUserDep) -> dict:
    rows = await gateway.rpc("admin_users_directory", {}, token=user.access_token)
    return {"items": rows, "count": len(rows)}


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    request: Request,
    gateway: GatewayDep,
    user: AdminUserDep,
) -> dict:
    order = await gateway.select(
        "orders",
        columns="id,status,buyer_id",
        filters={"id": str(order_id)},
        token=user.access_token,
        admin=True,
        single=True,
    )
    if not isinstance(order, dict):
        raise AppError(404, "order_not_found", "Order not found")
    current_status = str(order.get("status"))
    if payload.status not in ORDER_TRANSITIONS.get(current_status, set()):
        raise AppError(
            409,
            "invalid_order_transition",
            f"An order cannot move from {current_status} to {payload.status}.",
        )
    rows = await gateway.update(
        "orders",
        {"status": payload.status},
        filters={"id": str(order_id), "status": current_status},
        token=user.access_token,
        admin=True,
    )
    if not rows:
        raise AppError(
            409,
            "order_changed",
            "This order changed while you were updating it. Refresh and try again.",
        )

    profiles = as_list(
        await gateway.select(
            "buyer_profiles",
            columns="contact_email,business_name",
            filters={"user_id": str(order["buyer_id"])},
            token=user.access_token,
            admin=True,
            limit=1,
        )
    )
    profile = profiles[0] if profiles else {}
    recipient = profile.get("contact_email")
    if recipient:
        try:
            await request.app.state.email.send(
                order_status_update(
                    name=str(profile.get("business_name") or "there"),
                    order_reference=str(order_id),
                    status=payload.status,
                    app_url=request.app.state.settings.app_base_url.rstrip("/"),
                ).to_message(str(recipient))
            )
        except Exception:
            logger.exception(
                "order_status_email_failed", order_id=str(order_id), status=payload.status
            )
    return rows[0]
