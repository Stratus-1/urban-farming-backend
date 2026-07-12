from uuid import UUID

from fastapi import APIRouter

from app.core.errors import AppError
from app.core.security import CurrentUserDep, GatewayDep
from app.schemas.common import MessageResponse
from app.schemas.communications import CalculatorPlanUpsert
from app.services.gardens import as_list

router = APIRouter(prefix="/calculator-plans", tags=["calculator plans"])


@router.get("")
async def list_plans(gateway: GatewayDep, user: CurrentUserDep) -> dict:
    rows = as_list(
        await gateway.select(
            "calculator_plans",
            token=user.access_token,
            filters={"user_id": user.id},
            order="updated_at.desc",
        )
    )
    return {"items": rows, "count": len(rows)}


@router.put("")
async def upsert_plan(
    payload: CalculatorPlanUpsert, gateway: GatewayDep, user: CurrentUserDep
) -> dict:
    rows = await gateway.insert(
        "calculator_plans",
        {"user_id": str(user.id), **payload.model_dump(mode="json")},
        token=user.access_token,
        upsert=True,
        on_conflict="user_id,calculator_type,title",
    )
    return rows[0]


@router.delete("/{plan_id}", response_model=MessageResponse)
async def delete_plan(plan_id: UUID, gateway: GatewayDep, user: CurrentUserDep) -> MessageResponse:
    existing = await gateway.select(
        "calculator_plans",
        token=user.access_token,
        filters={"id": plan_id, "user_id": user.id},
        single=True,
    )
    if not existing:
        raise AppError(404, "plan_not_found", "Calculator plan not found")
    await gateway.delete(
        "calculator_plans",
        token=user.access_token,
        filters={"id": plan_id, "user_id": user.id},
    )
    return MessageResponse(message="Plan deleted")
