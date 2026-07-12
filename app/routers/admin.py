import asyncio

from fastapi import APIRouter, Query

from app.core.security import AdminUserDep, GatewayDep

router = APIRouter(prefix="/admin", tags=["admin"])


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
