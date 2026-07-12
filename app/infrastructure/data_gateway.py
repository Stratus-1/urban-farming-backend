from typing import Any, Protocol


class DataGateway(Protocol):
    async def close(self) -> None: ...

    async def ping(self) -> bool: ...

    async def select(
        self,
        table: str,
        *,
        token: str | None = None,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        single: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any] | None: ...

    async def insert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        token: str | None = None,
        upsert: bool = False,
        on_conflict: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def update(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        filters: dict[str, Any],
        token: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def delete(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        token: str | None = None,
    ) -> None: ...

    async def rpc(self, name: str, payload: dict[str, Any], *, token: str | None = None) -> Any: ...


PUBLIC_TABLES = {
    "crops",
    "inventory_aggregate",
    "grower_events",
    "grower_dashboard_tips",
    "community_spotlights",
    "grower_impact_factors",
    "green_point_rules",
}

ALLOWED_TABLES = PUBLIC_TABLES | {
    "buyer_profiles",
    "calculator_plans",
    "collections",
    "contact_messages",
    "crop_batches",
    "garden_activity_logs",
    "garden_requests",
    "garden_tasks",
    "green_point_transactions",
    "grower_event_registrations",
    "grower_stats",
    "harvests",
    "inspection_assignments",
    "inspection_checklist_items",
    "inspection_photos",
    "inspection_reports",
    "inspectors",
    "installations",
    "newsletter_subscriptions",
    "order_items",
    "orders",
    "profiles",
    "properties",
    "user_roles",
    "user_settings",
}

ALLOWED_RPCS = {
    "admin_dashboard_order_status",
    "admin_dashboard_overview",
    "admin_dashboard_recent_messages",
    "admin_dashboard_recent_orders",
    "admin_dashboard_summary",
    "admin_dashboard_top_crops",
    "admin_dashboard_trends",
    "admin_users_directory",
    "admin_users_trends",
    "apply_inspection_request_decision",
    "start_inspection_report",
    "submit_inspection_report",
}


def ensure_table_allowed(table: str) -> None:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Unsupported table: {table}")


def ensure_rpc_allowed(name: str) -> None:
    if name not in ALLOWED_RPCS:
        raise ValueError(f"Unsupported RPC: {name}")
