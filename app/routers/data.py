from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.security import CurrentUserDep, GatewayDep
from app.infrastructure.data_gateway import PUBLIC_TABLES

router = APIRouter(prefix="/data", tags=["data"])

OWNER_COLUMNS = {
    "buyer_profiles": "user_id",
    "calculator_plans": "user_id",
    "collections": "owner_id",
    "contact_messages": "user_id",
    "crop_batches": "owner_id",
    "garden_activity_logs": "owner_id",
    "garden_requests": "owner_id",
    "garden_tasks": "owner_id",
    "green_point_transactions": "owner_id",
    "grower_event_registrations": "user_id",
    "grower_stats": "user_id",
    "harvests": "owner_id",
    "installations": "owner_id",
    "orders": "buyer_id",
    "profiles": "id",
    "properties": "owner_id",
    "user_roles": "user_id",
    "user_settings": "user_id",
}
ADMIN_READ_TABLES = {
    "inspection_assignments", "inspection_checklist_items", "inspection_photos",
    "inspection_reports", "inspectors", "operational_workflows", "order_items",
    "workflow_stages", "workflow_stage_events",
}
ADMIN_MUTATION_TABLES = {
    "garden_requests", "inspection_assignments", "installations", "properties",
}
USER_MUTATION_TABLES = {
    "buyer_profiles", "calculator_plans", "garden_activity_logs", "garden_requests",
    "garden_tasks", "grower_event_registrations", "installations", "profiles", "properties",
    "user_settings",
}
ADMIN_RPCS = {
    "admin_dashboard_order_status", "admin_dashboard_overview",
    "admin_dashboard_recent_messages", "admin_dashboard_recent_orders",
    "admin_dashboard_summary", "admin_dashboard_top_crops", "admin_dashboard_trends",
    "admin_users_directory", "admin_users_trends", "apply_inspection_request_decision",
}
INSPECTOR_RPCS = {"start_inspection_report", "submit_inspection_report"}


class DataQuery(BaseModel):
    table: str
    columns: str = "*"
    filters: dict[str, Any] = Field(default_factory=dict)
    order: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    single: bool = False
    count: bool = False


class DataMutation(BaseModel):
    operation: Literal["insert", "update", "delete", "upsert"]
    table: str
    payload: dict[str, Any] | list[dict[str, Any]] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    on_conflict: str | None = None


class RpcRequest(BaseModel):
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)


def _is_admin(user: Any) -> bool:
    return user.has_any_role("admin", "operator")


def _scoped_filters(table: str, filters: dict[str, Any], user: Any) -> dict[str, Any]:
    if _is_admin(user):
        return filters
    owner_column = OWNER_COLUMNS.get(table)
    if owner_column:
        return {**filters, owner_column: str(user.id)}
    if table in PUBLIC_TABLES:
        return filters
    raise AppError(403, "table_forbidden", "You cannot access this data")


@router.post("/query")
async def query_data(payload: DataQuery, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    if payload.table in ADMIN_READ_TABLES and not _is_admin(user):
        raise AppError(403, "table_forbidden", "Administrator access is required")
    filters = _scoped_filters(payload.table, payload.filters, user)
    # Cloud SQL mode does not emulate PostgREST relationship expansion. A legacy
    # select containing `*` or a nested relationship must therefore return the
    # complete base row, never pass `*` through the identifier quoting branch.
    columns = (
        "*"
        if "*" in payload.columns or "(" in payload.columns or ")" in payload.columns
        else payload.columns
    )
    data = await gateway.select(
        payload.table, token=user.access_token, columns=columns, filters=filters,
        order=payload.order, limit=payload.limit, single=payload.single,
    )
    count = (1 if data else 0) if payload.single else len(data or [])
    return {"data": None if payload.count else data, "count": count if payload.count else None}


@router.post("/mutate")
async def mutate_data(payload: DataMutation, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    allowed = payload.table in USER_MUTATION_TABLES or (
        _is_admin(user) and payload.table in ADMIN_MUTATION_TABLES
    )
    if not allowed:
        raise AppError(403, "table_forbidden", "You cannot modify this data")
    filters = _scoped_filters(payload.table, payload.filters, user)
    token = user.access_token
    if payload.operation == "delete":
        await gateway.delete(payload.table, filters=filters, token=token)
        return {"data": None}
    if payload.payload is None:
        raise AppError(422, "payload_required", "A mutation payload is required")
    if payload.operation == "update":
        if not isinstance(payload.payload, dict):
            raise AppError(422, "invalid_payload", "Update payload must be an object")
        rows = await gateway.update(payload.table, payload.payload, filters=filters, token=token)
    else:
        mutation_payload = payload.payload
        owner_column = OWNER_COLUMNS.get(payload.table)
        if owner_column and not _is_admin(user):
            source = mutation_payload if isinstance(mutation_payload, list) else [mutation_payload]
            mutation_payload = [{**row, owner_column: str(user.id)} for row in source]
            if not isinstance(payload.payload, list):
                mutation_payload = mutation_payload[0]
        rows = await gateway.insert(
            payload.table, mutation_payload, token=token,
            upsert=payload.operation == "upsert", on_conflict=payload.on_conflict,
        )
    return {"data": rows}


@router.post("/rpc")
async def call_rpc(payload: RpcRequest, gateway: GatewayDep, user: CurrentUserDep) -> dict:
    if payload.name in ADMIN_RPCS and not _is_admin(user):
        raise AppError(403, "rpc_forbidden", "Administrator access is required")
    if payload.name in INSPECTOR_RPCS and not user.has_any_role("inspector", "admin", "operator"):
        raise AppError(403, "rpc_forbidden", "Inspector access is required")
    if payload.name not in ADMIN_RPCS | INSPECTOR_RPCS:
        raise AppError(403, "rpc_forbidden", "This operation is not available")
    return {"data": await gateway.rpc(payload.name, payload.payload, token=user.access_token)}
