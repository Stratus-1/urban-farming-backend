from decimal import Decimal

from fastapi import APIRouter

from app.core.security import CurrentUserDep, GatewayDep
from app.schemas.commerce import OrderCreate
from app.services.gardens import as_list

router = APIRouter(tags=["commerce"])


@router.get("/marketplace/inventory")
async def inventory(gateway: GatewayDep) -> dict:
    rows = as_list(await gateway.select("inventory_aggregate", order="name.asc"))
    return {"items": rows, "count": len(rows)}


@router.get("/orders")
async def list_orders(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    filters = {} if user.has_any_role("admin", "operator") else {"buyer_id": user.id}
    rows = as_list(
        await gateway.select(
            "orders", token=user.access_token, filters=filters, order="created_at.desc"
        )
    )
    return {"items": rows, "count": len(rows)}


@router.post("/orders", status_code=201)
async def create_order(payload: OrderCreate, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    total = sum(
        Decimal(str(item.quantity_kg)) * Decimal(str(item.unit_price)) for item in payload.items
    )
    order_rows = await gateway.insert(
        "orders",
        {
            "buyer_id": str(user.id),
            "status": "pending",
            "total": str(total),
            "delivery_date": payload.delivery_date.isoformat() if payload.delivery_date else None,
            "notes": payload.notes,
        },
        token=user.access_token,
    )
    order = order_rows[0]
    await gateway.insert(
        "order_items",
        [{"order_id": order["id"], **item.model_dump(mode="json")} for item in payload.items],
        token=user.access_token,
    )
    return order
