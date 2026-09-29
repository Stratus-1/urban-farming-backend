import json
import re
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.errors import AppError
from app.infrastructure.data_gateway import ensure_rpc_allowed, ensure_table_allowed

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
FILTER_OPERATORS = {
    "eq": "=",
    "neq": "!=",
    "gte": ">=",
    "lte": "<=",
    "gt": ">",
    "lt": "<",
    "ilike": "ILIKE",
}

ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

POSTGRES_TIMESTAMP_TYPES = {
    "timestamp with time zone",
    "timestamp without time zone",
}
POSTGRES_TIME_TYPES = {
    "time with time zone",
    "time without time zone",
}


def coerce_filter_value(value: Any) -> Any:
    """Convert JSON-safe ISO timestamps into values asyncpg can bind to TIMESTAMPTZ."""
    if isinstance(value, str) and ISO_DATETIME.fullmatch(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def bind_value(parameter: str, value: Any) -> tuple[str, Any]:
    """Return SQL and driver-safe values for dynamically generated statements."""
    if isinstance(value, dict):
        return f"CAST(:{parameter} AS JSONB)", json.dumps(value)
    return f":{parameter}", value


def coerce_column_value(value: Any, data_type: str | None) -> Any:
    """Convert JSON temporal strings to the Python values required by asyncpg.

    The compatibility data endpoint accepts JSON, so dates and timestamps arrive as
    strings. SQLAlchemy reflects the target PostgreSQL type when preparing the dynamic
    statement, and asyncpg then requires the corresponding Python temporal object.
    """
    if not isinstance(value, str) or not data_type:
        return value
    try:
        if data_type == "date":
            return date.fromisoformat(value)
        if data_type in POSTGRES_TIMESTAMP_TYPES:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if data_type == "timestamp without time zone" and parsed.tzinfo is not None:
                return parsed.replace(tzinfo=None)
            return parsed
        if data_type in POSTGRES_TIME_TYPES:
            parsed_time = time.fromisoformat(value.replace("Z", "+00:00"))
            if data_type == "time without time zone" and parsed_time.tzinfo is not None:
                return parsed_time.replace(tzinfo=None)
            return parsed_time
    except ValueError as error:
        raise AppError(
            422,
            "invalid_temporal_value",
            f"Invalid {data_type} value",
        ) from error
    return value


def quote_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value}")
    return f'"{value}"'


def build_filters(filters: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    parameters: dict[str, Any] = {}
    for index, (key, raw_value) in enumerate((filters or {}).items()):
        field = quote_identifier(key)
        parameter = f"filter_{index}"
        if raw_value is None:
            clauses.append(f"{field} IS NULL")
            continue
        if isinstance(raw_value, (list, tuple, set)):
            values = list(raw_value)
            placeholders = []
            for item_index, item in enumerate(values):
                item_parameter = f"{parameter}_{item_index}"
                parameters[item_parameter] = coerce_filter_value(item)
                placeholders.append(f":{item_parameter}")
            clauses.append(f"{field} IN ({', '.join(placeholders)})" if values else "FALSE")
            continue

        operator = "="
        value = raw_value
        if isinstance(raw_value, str) and "." in raw_value:
            candidate, candidate_value = raw_value.split(".", 1)
            if candidate in FILTER_OPERATORS:
                operator = FILTER_OPERATORS[candidate]
                value = candidate_value
            elif candidate == "is" and candidate_value == "null":
                clauses.append(f"{field} IS NULL")
                continue
        clauses.append(f"{field} {operator} :{parameter}")
        parameters[parameter] = coerce_filter_value(value)

    return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), parameters


class PostgresGateway:
    async def submit_inspection_for_approval(
        self,
        *,
        report_id: UUID,
        assignment_id: UUID,
        inspector_id: UUID,
        assessment: dict[str, Any],
        token: str | None,
    ) -> dict[str, Any]:
        """Validate evidence and submit report/assignment as one Cloud SQL transaction."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            report = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, assignment_id, inspector_id, assessment_status "
                            "FROM public.inspection_reports WHERE id=:report_id FOR UPDATE"
                        ),
                        {"report_id": report_id},
                    )
                )
                .mappings()
                .first()
            )
            if (
                report is None
                or str(report["assignment_id"]) != str(assignment_id)
                or str(report["inspector_id"]) != str(inspector_id)
            ):
                raise AppError(404, "inspection_report_not_found", "Inspection report not found")
            if report["assessment_status"] == "submitted_for_approval":
                raise AppError(
                    409,
                    "assessment_already_submitted",
                    "This assessment is already awaiting approval",
                )
            assignment = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, status FROM public.inspection_assignments "
                            "WHERE id=:assignment_id "
                            "AND inspector_id=:inspector_id FOR UPDATE"
                        ),
                        {"assignment_id": assignment_id, "inspector_id": inspector_id},
                    )
                )
                .mappings()
                .first()
            )
            if assignment is None:
                raise AppError(
                    404, "inspection_assignment_not_found", "Inspection assignment not found"
                )
            items = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, requires_photo, result "
                            "FROM public.inspection_checklist_items "
                            "WHERE report_id=:report_id FOR UPDATE"
                        ),
                        {"report_id": report_id},
                    )
                )
                .mappings()
                .all()
            )
            if not items:
                raise AppError(
                    409,
                    "inspection_checklist_missing",
                    "The inspection checklist is not ready. Reopen the inspection and try again.",
                )
            if any(item["requires_photo"] and item["result"] in (None, "na") for item in items):
                raise AppError(
                    422,
                    "inspection_evidence_incomplete",
                    "Complete every required inspection item and attach its site photo "
                    "before submitting.",
                )
            missing = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.inspection_checklist_items i "
                    "WHERE i.report_id=:report_id AND i.requires_photo AND NOT EXISTS "
                    "(SELECT 1 FROM public.inspection_photos p WHERE p.report_id=i.report_id "
                    "AND p.checklist_item_id=i.id))"
                ),
                {"report_id": report_id},
            )
            if missing:
                raise AppError(
                    422,
                    "inspection_evidence_incomplete",
                    "Complete every required inspection item and attach its site photo "
                    "before submitting.",
                )
            values = dict(assessment)
            values.update(report_id=report_id, assignment_id=assignment_id)
            for key in ("risks", "measurements", "score_breakdown"):
                values[key] = json.dumps(values[key])
            row = (
                (
                    await connection.execute(
                        text(
                            "UPDATE public.inspection_reports SET notes=:notes, "
                            "gps_lat=:gps_lat, gps_lng=:gps_lng, "
                            "sunlight_hours=:sunlight_hours, water_access=:water_access, "
                            "usable_space_m2=:usable_space_m2, "
                            "installation_types=:installation_types, "
                            "measurements=CAST(:measurements AS jsonb), "
                            "risks=CAST(:risks AS jsonb), suitability_score=:suitability_score, "
                            "score_breakdown=CAST(:score_breakdown AS jsonb), "
                            "suitability_band=:suitability_band, "
                            "recommended_crops=:recommended_crops, "
                            "recommended_infrastructure=:recommended_infrastructure, "
                            "assessment_status='submitted_for_approval', "
                            "overall_status=:overall_status, "
                            "follow_up_required=:follow_up_required, "
                            "submitted_at=:submitted_at, updated_at=now() "
                            "WHERE id=:report_id RETURNING *"
                        ),
                        values,
                    )
                )
                .mappings()
                .one()
            )
            await connection.execute(
                text(
                    "UPDATE public.inspection_assignments SET status='completed', "
                    "completed_at=:submitted_at, "
                    "updated_at=now() WHERE id=:assignment_id"
                ),
                values,
            )
            return dict(row)

    """Cloud SQL adapter. API authorization replaces browser-side RLS in this mode."""

    def __init__(self, database_url: str, pool_size: int = 5, max_overflow: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self._column_types: dict[str, dict[str, str]] = {}

    async def close(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> bool:
        async with self.engine.connect() as connection:
            return bool(await connection.scalar(text("select true")))

    async def _table_column_types(self, table: str) -> dict[str, str]:
        cached = self._column_types.get(table)
        if cached is not None:
            return cached
        statement = text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(statement, {"table": table})).mappings().all()
        column_types = {str(row["column_name"]): str(row["data_type"]) for row in rows}
        self._column_types[table] = column_types
        return column_types

    async def ensure_auth_user(self, payload: dict[str, Any]) -> None:
        """Keep the Cloud SQL auth compatibility row aligned during staged auth migration."""
        statement = text(
            """
            INSERT INTO auth.users (
              id, email, raw_app_meta_data, raw_user_meta_data,
              email_confirmed_at, last_sign_in_at, created_at, updated_at
            ) VALUES (
              :id, :email, :app_metadata, :user_metadata,
              :email_confirmed_at, :last_sign_in_at, COALESCE(:created_at, now()), now()
            )
            ON CONFLICT (id) DO UPDATE SET
              email = EXCLUDED.email,
              raw_app_meta_data = EXCLUDED.raw_app_meta_data,
              raw_user_meta_data = EXCLUDED.raw_user_meta_data,
              email_confirmed_at = EXCLUDED.email_confirmed_at,
              last_sign_in_at = EXCLUDED.last_sign_in_at,
              updated_at = now()
            """
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                statement,
                {
                    "id": payload["id"],
                    "email": payload.get("email"),
                    "app_metadata": payload.get("app_metadata") or {},
                    "user_metadata": payload.get("user_metadata") or {},
                    "email_confirmed_at": payload.get("email_confirmed_at"),
                    "last_sign_in_at": payload.get("last_sign_in_at"),
                    "created_at": payload.get("created_at"),
                },
            )

    @staticmethod
    async def _set_identity(connection: Any, token: str | None) -> None:
        if not token or token == "development":
            return
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return
        subject = str(claims.get("sub") or "")
        if subject:
            await connection.execute(
                text("SELECT set_config('request.jwt.claim.sub', :subject, true)"),
                {"subject": subject},
            )

    async def select(
        self,
        table: str,
        *,
        token: str | None = None,
        admin: bool = False,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        single: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        ensure_table_allowed(table)
        table_sql = f"public.{quote_identifier(table)}"
        if columns == "*":
            columns_sql = "*"
        else:
            requested_columns = [item.strip() for item in columns.split(",")]
            if any("(" in item or ")" in item for item in requested_columns):
                raise AppError(400, "unsupported_select", "Nested selects require Supabase mode")
            columns_sql = ", ".join(quote_identifier(item) for item in requested_columns)

        where_sql, parameters = build_filters(filters)
        order_sql = ""
        if order:
            order_column, _, direction = order.partition(".")
            order_sql = (
                f" ORDER BY {quote_identifier(order_column)} "
                f"{'DESC' if direction == 'desc' else 'ASC'}"
            )
        limit_sql = ""
        if limit is not None:
            parameters["row_limit"] = limit
            limit_sql = " LIMIT :row_limit"
        statement = text(f"SELECT {columns_sql} FROM {table_sql}{where_sql}{order_sql}{limit_sql}")
        async with self.engine.connect() as connection:
            await self._set_identity(connection, token)
            rows = (await connection.execute(statement, parameters)).mappings().all()
        data = [dict(row) for row in rows]
        return (data[0] if data else None) if single else data

    async def select_garden_requests_for_help_center(
        self, tenant_scope_refs: list[str], *, limit: int
    ) -> list[dict[str, Any]]:
        """Read only garden requests joined to explicit, pre-approved source tenant scopes."""
        if not tenant_scope_refs:
            return []
        statement = text(
            """
            SELECT request.id, request.owner_id, request.status,
                   request.created_at, request.updated_at
            FROM public.garden_requests AS request
            INNER JOIN public.help_center_tenant_scopes AS scope
              ON scope.owner_id = request.owner_id
            WHERE scope.tenant_scope_ref = ANY(CAST(:tenant_scope_refs AS text[]))
            ORDER BY request.updated_at ASC
            LIMIT :row_limit
            """
        )
        async with self.engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        statement,
                        {"tenant_scope_refs": tenant_scope_refs, "row_limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def insert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        token: str | None = None,
        admin: bool = False,
        upsert: bool = False,
        on_conflict: str | None = None,
    ) -> list[dict[str, Any]]:
        ensure_table_allowed(table)
        rows = payload if isinstance(payload, list) else [payload]
        if not rows:
            return []
        columns = list(rows[0])
        if any(set(row) != set(columns) for row in rows):
            raise ValueError("Bulk insert rows must contain the same fields")
        column_types = await self._table_column_types(table)
        column_sql = ", ".join(quote_identifier(item) for item in columns)
        values_sql: list[str] = []
        parameters: dict[str, Any] = {}
        for row_index, row in enumerate(rows):
            placeholders = []
            for column_name in columns:
                parameter = f"row_{row_index}_{column_name}"
                value = coerce_column_value(row[column_name], column_types.get(column_name))
                placeholder, bound_value = bind_value(parameter, value)
                placeholders.append(placeholder)
                parameters[parameter] = bound_value
            values_sql.append(f"({', '.join(placeholders)})")

        conflict_sql = ""
        if upsert:
            if not on_conflict:
                raise ValueError("on_conflict is required for upsert")
            conflict_columns = [quote_identifier(item.strip()) for item in on_conflict.split(",")]
            update_columns = [
                item for item in columns if quote_identifier(item) not in conflict_columns
            ]
            assignments = ", ".join(
                f"{quote_identifier(item)} = EXCLUDED.{quote_identifier(item)}"
                for item in update_columns
            )
            conflict_sql = (
                f" ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE SET {assignments}"
                if assignments
                else f" ON CONFLICT ({', '.join(conflict_columns)}) DO NOTHING"
            )
        statement = text(
            f"INSERT INTO public.{quote_identifier(table)} ({column_sql}) "
            f"VALUES {', '.join(values_sql)}{conflict_sql} RETURNING *"
        )
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            result = await connection.execute(statement, parameters)
            return [dict(row) for row in result.mappings().all()]

    async def update(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        filters: dict[str, Any],
        token: str | None = None,
        admin: bool = False,
    ) -> list[dict[str, Any]]:
        ensure_table_allowed(table)
        column_types = await self._table_column_types(table)
        assignments = []
        parameters: dict[str, Any] = {}
        for index, (key, value) in enumerate(payload.items()):
            parameter = f"value_{index}"
            value = coerce_column_value(value, column_types.get(key))
            placeholder, bound_value = bind_value(parameter, value)
            assignments.append(f"{quote_identifier(key)} = {placeholder}")
            parameters[parameter] = bound_value
        where_sql, filter_parameters = build_filters(filters)
        parameters.update(filter_parameters)
        statement = text(
            f"UPDATE public.{quote_identifier(table)} SET {', '.join(assignments)} "
            f"{where_sql} RETURNING *"
        )
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            result = await connection.execute(statement, parameters)
            return [dict(row) for row in result.mappings().all()]

    async def delete(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        token: str | None = None,
        admin: bool = False,
    ) -> None:
        ensure_table_allowed(table)
        where_sql, parameters = build_filters(filters)
        if not where_sql:
            raise ValueError("Delete operations require at least one filter")
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            await connection.execute(
                text(f"DELETE FROM public.{quote_identifier(table)}{where_sql}"), parameters
            )

    async def rpc(
        self, name: str, payload: dict[str, Any], *, token: str | None = None, admin: bool = False
    ) -> Any:
        ensure_rpc_allowed(name)
        arguments = ", ".join(f"{quote_identifier(key)} => :{key}" for key in payload)
        async with self.engine.connect() as connection:
            await self._set_identity(connection, token)
            result = await connection.execute(
                text(f"SELECT * FROM public.{quote_identifier(name)}({arguments})"), payload
            )
            return [dict(row) for row in result.mappings().all()]

    async def start_inspection_report(
        self,
        *,
        assignment_id: UUID,
        inspector_id: UUID,
        gps_lat: float | None,
        gps_lng: float | None,
        checklist_template: tuple[tuple[str, str, bool, int], ...],
        token: str | None,
    ) -> dict[str, Any]:
        """Start or resume an assigned inspection atomically in Cloud SQL."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            assignment = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, inspector_id, garden_id, status, started_at "
                            "FROM public.inspection_assignments "
                            "WHERE id = :assignment_id AND inspector_id = :inspector_id "
                            "FOR UPDATE"
                        ),
                        {"assignment_id": assignment_id, "inspector_id": inspector_id},
                    )
                )
                .mappings()
                .first()
            )
            if assignment is None:
                raise AppError(
                    404, "inspection_assignment_not_found", "Inspection assignment not found"
                )

            report = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM public.inspection_reports "
                            "WHERE assignment_id = :assignment_id LIMIT 1"
                        ),
                        {"assignment_id": assignment_id},
                    )
                )
                .mappings()
                .first()
            )
            if report is None:
                report = (
                    (
                        await connection.execute(
                            text(
                                "INSERT INTO public.inspection_reports "
                                "(assignment_id, inspector_id, garden_id, overall_status, notes, "
                                "gps_lat, gps_lng, started_at) "
                                "VALUES (:assignment_id, :inspector_id, :garden_id, 'pending', "
                                "NULL, :gps_lat, :gps_lng, now()) RETURNING *"
                            ),
                            {
                                "assignment_id": assignment_id,
                                "inspector_id": inspector_id,
                                "garden_id": assignment["garden_id"],
                                "gps_lat": gps_lat,
                                "gps_lng": gps_lng,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )

            await connection.execute(
                text(
                    "UPDATE public.inspection_assignments "
                    "SET status = CASE WHEN status IN ('pending', 'in_progress') "
                    "THEN 'in_progress' ELSE status END, "
                    "started_at = COALESCE(started_at, now()), updated_at = now() "
                    "WHERE id = :assignment_id"
                ),
                {"assignment_id": assignment_id},
            )

            has_checklist = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.inspection_checklist_items "
                    "WHERE report_id = :report_id)"
                ),
                {"report_id": report["id"]},
            )
            if not has_checklist:
                await connection.execute(
                    text(
                        "INSERT INTO public.inspection_checklist_items "
                        "(report_id, category, item_name, result, comment, "
                        "requires_photo, sort_order) "
                        "VALUES (:report_id, :category, :item_name, 'na', NULL, "
                        ":requires_photo, :sort_order)"
                    ),
                    [
                        {
                            "report_id": report["id"],
                            "category": category,
                            "item_name": item_name,
                            "requires_photo": requires_photo,
                            "sort_order": sort_order,
                        }
                        for category, item_name, requires_photo, sort_order in checklist_template
                    ],
                )
            return dict(report)

    async def schedule_garden_request_inspection(
        self,
        request_id: UUID,
        schedule: dict[str, Any],
        actor_id: UUID,
        *,
        token: str | None,
    ) -> dict[str, Any]:
        """Create/link a property and its inspection assignment atomically and idempotently."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            request = (
                (
                    await connection.execute(
                        text("SELECT * FROM public.garden_requests WHERE id = :id FOR UPDATE"),
                        {"id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if request is None:
                raise AppError(404, "request_not_found", "Garden request not found")
            if request["status"] not in {"submitted", "inspection_scheduled"}:
                raise AppError(
                    409,
                    "invalid_request_transition",
                    f"Cannot schedule an inspection for a {request['status']} request.",
                )

            inspector = (
                (
                    await connection.execute(
                        text(
                            "SELECT id FROM public.inspectors WHERE id = :id AND status = 'active'"
                        ),
                        {"id": schedule["inspector_id"]},
                    )
                )
                .mappings()
                .first()
            )
            if inspector is None:
                raise AppError(422, "inspector_unavailable", "Select an active inspector.")

            property_id = request["property_id"]
            if property_id is None:
                property_row = (
                    (
                        await connection.execute(
                            text(
                                "INSERT INTO public.properties "
                                "(owner_id, label, address, city, lat, lng, available_space_m2, "
                                "sunlight_hours, notes) VALUES (:owner_id, :label, "
                                ":address, :city, "
                                ":lat, :lng, :available_space_m2, :sunlight_hours, :notes) "
                                "RETURNING id"
                            ),
                            {
                                "owner_id": request["owner_id"],
                                "label": request["label"],
                                "address": request["address"],
                                "city": request["city"],
                                "lat": request["lat"],
                                "lng": request["lng"],
                                "available_space_m2": request["available_space_m2"],
                                "sunlight_hours": request["sunlight_hours"],
                                "notes": (
                                    (request["details"] or {}).get("notes")
                                    if isinstance(request["details"], dict)
                                    else None
                                )
                                or request["admin_notes"],
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                property_id = property_row["id"]
            else:
                property_row = (
                    (
                        await connection.execute(
                            text(
                                "SELECT owner_id FROM public.properties WHERE id = :id FOR UPDATE"
                            ),
                            {"id": property_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if property_row is None or property_row["owner_id"] != request["owner_id"]:
                    raise AppError(
                        409,
                        "garden_property_mismatch",
                        "The request is linked to an unavailable garden record.",
                    )

            assignment = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, status FROM public.inspection_assignments "
                            "WHERE garden_id = :garden_id AND status IN ('pending', 'in_progress') "
                            "ORDER BY updated_at DESC LIMIT 1 FOR UPDATE"
                        ),
                        {"garden_id": property_id},
                    )
                )
                .mappings()
                .first()
            )
            assignment_values = {
                "inspector_id": schedule["inspector_id"],
                "garden_id": property_id,
                "due_date": schedule["due_date"],
                "scheduled_for": schedule["scheduled_for"],
                "priority": schedule["priority"],
                "admin_notes": schedule["admin_notes"],
            }
            if assignment:
                assignment_row = (
                    (
                        await connection.execute(
                            text(
                                "UPDATE public.inspection_assignments "
                                "SET inspector_id = :inspector_id, "
                                "due_date = :due_date, scheduled_for = :scheduled_for, "
                                "priority = :priority, admin_notes = :admin_notes, "
                                "updated_at = now() WHERE id = :id RETURNING *"
                            ),
                            {**assignment_values, "id": assignment["id"]},
                        )
                    )
                    .mappings()
                    .first()
                )
            else:
                assignment_row = (
                    (
                        await connection.execute(
                            text(
                                "INSERT INTO public.inspection_assignments "
                                "(inspector_id, garden_id, due_date, scheduled_for, "
                                "priority, status, "
                                "admin_notes) VALUES (:inspector_id, :garden_id, :due_date, "
                                ":scheduled_for, :priority, 'pending', :admin_notes) RETURNING *"
                            ),
                            assignment_values,
                        )
                    )
                    .mappings()
                    .first()
                )

            details = request["details"] if isinstance(request["details"], dict) else {}
            details = {
                **details,
                "inspectionAssignment": {
                    "assignmentId": str(assignment_row["id"]),
                    "inspectorId": str(schedule["inspector_id"]),
                    "dueDate": schedule["due_date"].isoformat(),
                    "scheduledFor": schedule["scheduled_for"].isoformat(),
                    "priority": schedule["priority"],
                    "focusAreas": schedule["focus_areas"],
                    "focusBrief": schedule["focus_brief"],
                    "accessInstructions": schedule["access_instructions"],
                    "assignedBy": str(actor_id),
                },
            }
            request_columns = await self._table_column_types("garden_requests")
            admin_notes = schedule["admin_notes"] or request["admin_notes"]
            now = datetime.now(UTC)
            request_values: dict[str, Any] = {
                "property_id": property_id,
                "admin_notes": admin_notes,
                "details": details,
            }
            if request["status"] == "submitted":
                request_values.update(
                    {
                        "status": "inspection_scheduled",
                        "reviewed_by": actor_id,
                        "reviewed_at": now,
                    }
                )
            request_assignments: list[str] = []
            request_parameters: dict[str, Any] = {
                "request_id": request_id,
                "expected_status": request["status"],
            }
            for index, (key, value) in enumerate(request_values.items()):
                parameter = f"request_value_{index}"
                value = coerce_column_value(value, request_columns.get(key))
                expression, bound_value = bind_value(parameter, value)
                request_assignments.append(f"{quote_identifier(key)} = {expression}")
                request_parameters[parameter] = bound_value
            result = await connection.execute(
                text(
                    "UPDATE public.garden_requests SET "
                    + ", ".join(request_assignments)
                    + ", updated_at = now() WHERE id = :request_id "
                    "AND status = :expected_status RETURNING *"
                ),
                request_parameters,
            )
            updated_request = result.mappings().first()
            if not updated_request:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while the inspection was being scheduled.",
                )

            workflow_stages = [
                {
                    "stage_key": "property_details",
                    "status": "completed",
                    "evidence": {"address": request["address"], "property_id": property_id},
                    "next_action": None,
                },
                {
                    "stage_key": "preliminary_assessment",
                    "status": "completed",
                    "evidence": {"result": "manual_review_passed", "reviewed_by": actor_id},
                    "next_action": None,
                },
                {
                    "stage_key": "inspector_visit",
                    "status": "in_progress",
                    "evidence": {"assignment_id": assignment_row["id"]},
                    "next_action": "Complete the site visit and submit the inspection report.",
                },
            ]
            for stage_update in workflow_stages:
                stage = (
                    (
                        await connection.execute(
                            text(
                                "SELECT stage.id, stage.evidence, stage.started_at, "
                                "stage.completed_at FROM public.workflow_stages AS stage "
                                "JOIN public.operational_workflows AS workflow "
                                "ON workflow.id = stage.workflow_id "
                                "WHERE workflow.garden_request_id = :request_id "
                                "AND stage.stage_key = :stage_key FOR UPDATE OF stage"
                            ),
                            {"request_id": request_id, "stage_key": stage_update["stage_key"]},
                        )
                    )
                    .mappings()
                    .first()
                )
                if stage is None:
                    raise AppError(
                        409,
                        "workflow_stage_missing",
                        f"Workflow stage {stage_update['stage_key']} is missing.",
                    )
                prior_evidence = stage["evidence"]
                evidence = {
                    **(prior_evidence if isinstance(prior_evidence, dict) else {}),
                    **stage_update["evidence"],
                }
                stage_result = await connection.execute(
                    text(
                        "UPDATE public.workflow_stages SET status = :status, "
                        "owner_user_id = :actor_id, evidence = CAST(:evidence AS jsonb), "
                        "started_at = COALESCE(started_at, :now), "
                        "completed_at = CASE WHEN :status IN ('completed', 'rejected') "
                        "THEN COALESCE(completed_at, :now) ELSE completed_at END, "
                        "next_action = COALESCE(:next_action, next_action) "
                        "WHERE id = :stage_id RETURNING id"
                    ),
                    {
                        "status": stage_update["status"],
                        "actor_id": actor_id,
                        "evidence": json.dumps(evidence, default=str),
                        "now": now,
                        "next_action": stage_update["next_action"],
                        "stage_id": stage["id"],
                    },
                )
                if not stage_result.mappings().first():
                    raise AppError(
                        409,
                        "workflow_stage_update_failed",
                        f"Could not advance {stage_update['stage_key']}",
                    )
            return {
                "request": dict(updated_request),
                "assignment": dict(assignment_row),
            }

    async def update_garden_request_workflow(
        self,
        request_id: UUID,
        expected_status: str,
        request_payload: dict[str, Any],
        actor_id: UUID,
        stage_updates: list[dict[str, Any]],
        *,
        assignment_id: UUID | None = None,
        report_update: dict[str, Any] | None = None,
        token: str | None,
    ) -> dict[str, Any]:
        """Advance a request and its linked assessment/workflow in one transaction."""
        column_types = await self._table_column_types("garden_requests")
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            request = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, property_id, status FROM public.garden_requests "
                            "WHERE id = :request_id FOR UPDATE"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if request is None:
                raise AppError(404, "request_not_found", "Garden request not found")
            if request["status"] != expected_status:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while this update was being recorded.",
                )

            if request_payload.get("status") == "live":
                property_id = request["property_id"]
                approved_report = (
                    (
                        (
                            await connection.execute(
                                text(
                                    "SELECT id FROM public.inspection_reports "
                                    "WHERE garden_id = :property_id "
                                    "AND assessment_status = 'approved' "
                                    "LIMIT 1 FOR UPDATE"
                                ),
                                {"property_id": property_id},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if property_id
                    else None
                )
                installation = (
                    (
                        (
                            await connection.execute(
                                text(
                                    "SELECT id, installed_at FROM public.installations "
                                    "WHERE property_id = :property_id AND status = 'active' "
                                    "ORDER BY created_at ASC LIMIT 1 FOR UPDATE"
                                ),
                                {"property_id": property_id},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if property_id
                    else None
                )
                if not approved_report or not installation or not installation["installed_at"]:
                    raise AppError(
                        409,
                        "activation_requirements_missing",
                        "Finish the approved setup and record planted crops before activation.",
                    )
                batches = (
                    (
                        await connection.execute(
                            text(
                                "SELECT status, planted_at FROM public.crop_batches "
                                "WHERE installation_id = :installation_id FOR UPDATE"
                            ),
                            {"installation_id": installation["id"]},
                        )
                    )
                    .mappings()
                    .all()
                )
                if not batches:
                    raise AppError(
                        409,
                        "activation_requirements_missing",
                        "Finish the approved setup and record planted crops before activation.",
                    )
                if any(
                    batch["status"] != "growing" or not batch["planted_at"] for batch in batches
                ):
                    raise AppError(
                        409,
                        "planting_not_complete",
                        "Record planting before activating the garden.",
                    )

            if assignment_id is not None:
                assignment = (
                    (
                        await connection.execute(
                            text(
                                "SELECT id FROM public.inspection_assignments "
                                "WHERE id = :assignment_id AND garden_id = :property_id "
                                "AND status IN ('pending', 'in_progress') FOR UPDATE"
                            ),
                            {
                                "assignment_id": assignment_id,
                                "property_id": request["property_id"],
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if assignment is None:
                    raise AppError(
                        409,
                        "inspector_assignment_required",
                        "Assign an inspector before scheduling the visit.",
                    )

            if report_update is not None:
                notes_assignment = "notes = :notes, " if "notes" in report_update else ""
                report_result = await connection.execute(
                    text(
                        "UPDATE public.inspection_reports SET "
                        + notes_assignment
                        + "assessment_status = :status WHERE id = :report_id "
                        "AND assessment_status = 'submitted_for_approval' RETURNING id"
                    ),
                    report_update,
                )
                if not report_result.mappings().first():
                    raise AppError(
                        409,
                        "assessment_changed",
                        "The inspection assessment changed before this decision was saved.",
                    )

            request_assignments = []
            request_parameters: dict[str, Any] = {
                "request_id": request_id,
                "expected_status": expected_status,
            }
            for index, (key, value) in enumerate(request_payload.items()):
                parameter = f"request_value_{index}"
                value = coerce_column_value(value, column_types.get(key))
                expression, bound_value = bind_value(parameter, value)
                request_assignments.append(f"{quote_identifier(key)} = {expression}")
                request_parameters[parameter] = bound_value
            request_result = await connection.execute(
                text(
                    "UPDATE public.garden_requests SET "
                    + ", ".join(request_assignments)
                    + " WHERE id = :request_id AND status = :expected_status RETURNING *"
                ),
                request_parameters,
            )
            updated_request = request_result.mappings().first()
            if not updated_request:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while this update was being recorded.",
                )

            for stage_update in stage_updates:
                stage = (
                    (
                        await connection.execute(
                            text(
                                "SELECT stage.id, stage.evidence, stage.started_at, "
                                "stage.completed_at "
                                "FROM public.workflow_stages AS stage "
                                "JOIN public.operational_workflows AS workflow "
                                "ON workflow.id = stage.workflow_id "
                                "WHERE workflow.garden_request_id = :request_id "
                                "AND stage.stage_key = :stage_key FOR UPDATE OF stage"
                            ),
                            {"request_id": request_id, "stage_key": stage_update["stage_key"]},
                        )
                    )
                    .mappings()
                    .first()
                )
                if stage is None:
                    raise AppError(
                        409,
                        "workflow_stage_missing",
                        f"Workflow stage {stage_update['stage_key']} is missing.",
                    )
                prior_evidence = stage["evidence"]
                evidence = {
                    **(prior_evidence if isinstance(prior_evidence, dict) else {}),
                    **stage_update["evidence"],
                }
                now = datetime.now(UTC)
                stage_result = await connection.execute(
                    text(
                        "UPDATE public.workflow_stages SET status = :status, "
                        "owner_user_id = :actor_id, evidence = CAST(:evidence AS jsonb), "
                        "started_at = COALESCE(started_at, :now), "
                        "completed_at = CASE WHEN :status IN ('completed', 'rejected') "
                        "THEN COALESCE(completed_at, :now) ELSE completed_at END, "
                        "submitted_at = CASE WHEN :status = 'submitted' "
                        "THEN :now ELSE submitted_at END, "
                        "next_action = COALESCE(:next_action, next_action) "
                        "WHERE id = :stage_id RETURNING id"
                    ),
                    {
                        "status": stage_update["status"],
                        "actor_id": actor_id,
                        "evidence": json.dumps(evidence, default=str),
                        "now": now,
                        "next_action": stage_update.get("next_action"),
                        "stage_id": stage["id"],
                    },
                )
                if not stage_result.mappings().first():
                    raise AppError(
                        409,
                        "workflow_stage_update_failed",
                        f"Could not advance {stage_update['stage_key']}.",
                    )
            return dict(updated_request)

    async def complete_garden_installation(
        self,
        request_id: UUID,
        property_id: UUID,
        payload: dict[str, Any],
        actor_id: UUID,
        *,
        token: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Record the installation and advance its request in one transaction."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            request = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, owner_id, property_id, status FROM public.garden_requests "
                            "WHERE id = :request_id FOR UPDATE"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if request is None:
                raise AppError(404, "request_not_found", "Garden request not found")
            if request["status"] != "needing_implements" or request["property_id"] != property_id:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while installation was being recorded. "
                    "Refresh and try again.",
                )

            approved_report = (
                (
                    await connection.execute(
                        text(
                            "SELECT id FROM public.inspection_reports "
                            "WHERE garden_id = :property_id "
                            "AND assessment_status = 'approved' "
                            "LIMIT 1 FOR UPDATE"
                        ),
                        {"property_id": property_id},
                    )
                )
                .mappings()
                .first()
            )
            if approved_report is None:
                raise AppError(
                    409,
                    "inspection_approval_required",
                    "An approved site assessment is required.",
                )

            workflow_stages = (
                (
                    await connection.execute(
                        text(
                            "SELECT stage.id, stage.stage_key, stage.evidence, stage.started_at "
                            "FROM public.workflow_stages AS stage "
                            "INNER JOIN public.operational_workflows AS workflow "
                            "ON workflow.id = stage.workflow_id "
                            "WHERE workflow.garden_request_id = :request_id "
                            "AND stage.stage_key IN ('installation', 'crop_allocation') "
                            "FOR UPDATE OF stage"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .all()
            )
            stages_by_key = {stage["stage_key"]: stage for stage in workflow_stages}
            if "installation" not in stages_by_key or "crop_allocation" not in stages_by_key:
                raise AppError(
                    409,
                    "workflow_stage_missing",
                    "Workflow stages installation and crop_allocation are required.",
                )

            existing = (
                (
                    await connection.execute(
                        text(
                            "SELECT id FROM public.installations WHERE property_id = :property_id "
                            "ORDER BY created_at ASC LIMIT 1 FOR UPDATE"
                        ),
                        {"property_id": property_id},
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                installation = (
                    (
                        await connection.execute(
                            text(
                                "UPDATE public.installations SET owner_id = :owner_id, "
                                "install_type = :install_type, size_m2 = :size_m2, "
                                "capacity_units = :capacity_units, status = 'active', "
                                "installed_at = :installed_at, photos = CAST(:photos AS jsonb), "
                                "maintenance_notes = :maintenance_notes "
                                "WHERE id = :installation_id RETURNING *"
                            ),
                            {
                                **payload,
                                "installed_at": date.fromisoformat(payload["installed_at"]),
                                "photos": json.dumps(payload["photos"]),
                                "owner_id": request["owner_id"],
                                "installation_id": existing["id"],
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            else:
                installation = (
                    (
                        await connection.execute(
                            text(
                                "INSERT INTO public.installations "
                                "(owner_id, property_id, install_type, size_m2, capacity_units, "
                                "status, installed_at, photos, maintenance_notes) "
                                "VALUES (:owner_id, :property_id, :install_type, :size_m2, "
                                ":capacity_units, 'active', :installed_at, CAST(:photos AS jsonb), "
                                ":maintenance_notes) RETURNING *"
                            ),
                            {
                                **payload,
                                "installed_at": date.fromisoformat(payload["installed_at"]),
                                "photos": json.dumps(payload["photos"]),
                                "owner_id": request["owner_id"],
                                "property_id": property_id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            updated_request = (
                (
                    await connection.execute(
                        text(
                            "UPDATE public.garden_requests SET status = 'implements_installed' "
                            "WHERE id = :request_id RETURNING *"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .one()
            )
            for stage_key, status, next_action in (
                ("installation", "completed", None),
                ("crop_allocation", "ready", "Allocate approved crops to the installed garden."),
            ):
                stage = stages_by_key[stage_key]
                evidence = stage["evidence"] if isinstance(stage["evidence"], dict) else {}
                if stage_key == "installation":
                    evidence = {
                        **evidence,
                        "installation_id": str(installation["id"]),
                        "installed_at": payload["installed_at"],
                        "photos": payload["photos"],
                    }
                next_action_assignment = ", next_action = :next_action" if next_action else ""
                stage_update = await connection.execute(
                    text(
                        "UPDATE public.workflow_stages SET status = :status, "
                        "owner_user_id = :actor_id, evidence = CAST(:evidence AS jsonb), "
                        "started_at = COALESCE(started_at, now()), "
                        "completed_at = CASE WHEN :status = 'completed' THEN now() "
                        "ELSE completed_at END, updated_at = now()"
                        + next_action_assignment
                        + " WHERE id = :stage_id RETURNING id"
                    ),
                    {
                        "status": status,
                        "actor_id": actor_id,
                        "evidence": json.dumps(evidence),
                        "next_action": next_action,
                        "stage_id": stage["id"],
                    },
                )
                if not stage_update.mappings().first():
                    raise AppError(
                        409,
                        "workflow_stage_update_failed",
                        f"Could not advance {stage_key}.",
                    )
            return dict(updated_request), dict(installation)

    async def complete_garden_planting(
        self,
        request_id: UUID,
        planted_at: date,
        actor_id: UUID,
        *,
        token: str | None,
    ) -> dict[str, Any]:
        """Record planting and advance the request/workflow atomically."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            request = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, property_id, status FROM public.garden_requests "
                            "WHERE id = :request_id FOR UPDATE"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if request is None:
                raise AppError(404, "request_not_found", "Garden request not found")
            if request["status"] != "seeds":
                raise AppError(
                    409,
                    "allocation_required",
                    "Allocate crops before recording planting.",
                )
            if request["property_id"] is None:
                raise AppError(
                    409, "property_required", "A property must be linked before planting."
                )

            installation = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, installed_at FROM public.installations "
                            "WHERE property_id = :property_id AND status = 'active' "
                            "ORDER BY created_at ASC LIMIT 1 FOR UPDATE"
                        ),
                        {"property_id": request["property_id"]},
                    )
                )
                .mappings()
                .first()
            )
            if installation is None or installation["installed_at"] is None:
                raise AppError(
                    409,
                    "installation_not_complete",
                    "A completed physical installation is required.",
                )

            batches = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, status FROM public.crop_batches "
                            "WHERE installation_id = :installation_id FOR UPDATE"
                        ),
                        {"installation_id": installation["id"]},
                    )
                )
                .mappings()
                .all()
            )
            if not batches:
                raise AppError(
                    409,
                    "crop_allocation_required",
                    "Allocate at least one crop before planting.",
                )
            if any(batch["status"] not in {"planned", "growing"} for batch in batches):
                raise AppError(
                    409,
                    "crop_batch_state_invalid",
                    "Only planned crop batches can be planted.",
                )

            workflow_stage = (
                (
                    await connection.execute(
                        text(
                            "SELECT stage.id, stage.evidence, stage.started_at "
                            "FROM public.workflow_stages AS stage "
                            "INNER JOIN public.operational_workflows AS workflow "
                            "ON workflow.id = stage.workflow_id "
                            "WHERE workflow.garden_request_id = :request_id "
                            "AND stage.stage_key = 'maintenance_tasks' FOR UPDATE OF stage"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if workflow_stage is None:
                raise AppError(
                    409,
                    "workflow_stage_missing",
                    "Workflow stage maintenance_tasks is missing.",
                )

            batch_ids = [str(batch["id"]) for batch in batches]
            updated_batches = (
                (
                    await connection.execute(
                        text(
                            "UPDATE public.crop_batches SET status = 'growing', "
                            "planted_at = :planted_at "
                            "WHERE installation_id = :installation_id "
                            "AND status IN ('planned', 'growing') RETURNING id"
                        ),
                        {"planted_at": planted_at, "installation_id": installation["id"]},
                    )
                )
                .mappings()
                .all()
            )
            if len(updated_batches) != len(batches):
                raise AppError(
                    409,
                    "crop_batch_state_changed",
                    "Crop batches changed while planting was being recorded. "
                    "Refresh and try again.",
                )

            updated_request = (
                (
                    await connection.execute(
                        text(
                            "UPDATE public.garden_requests SET status = 'final_install' "
                            "WHERE id = :request_id AND status = 'seeds' RETURNING *"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if updated_request is None:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while planting was being recorded.",
                )

            prior_evidence = workflow_stage["evidence"]
            evidence = {
                **(prior_evidence if isinstance(prior_evidence, dict) else {}),
                "planted_at": planted_at.isoformat(),
                "crop_batch_ids": batch_ids,
            }
            updated_stage = await connection.execute(
                text(
                    "UPDATE public.workflow_stages SET status = 'in_progress', "
                    "owner_user_id = :actor_id, evidence = CAST(:evidence AS jsonb), "
                    "started_at = COALESCE(started_at, now()), updated_at = now() "
                    "WHERE id = :stage_id RETURNING id"
                ),
                {
                    "actor_id": actor_id,
                    "evidence": json.dumps(evidence),
                    "stage_id": workflow_stage["id"],
                },
            )
            if not updated_stage.mappings().first():
                raise AppError(
                    409,
                    "workflow_stage_update_failed",
                    "Could not advance maintenance_tasks.",
                )
            return dict(updated_request)

    async def complete_garden_allocation(
        self,
        request_id: UUID,
        expected_property_id: UUID,
        property_payload: dict[str, Any],
        approved_report_id: UUID,
        crop_rows: list[dict[str, Any]],
        detail_updates: dict[str, Any],
        admin_notes: str | None,
        actor_id: UUID,
        *,
        token: str | None,
    ) -> dict[str, Any]:
        """Allocate recommended crops and advance both workflow stages atomically."""
        async with self.engine.begin() as connection:
            await self._set_identity(connection, token)
            request = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, owner_id, property_id, status, details "
                            "FROM public.garden_requests WHERE id = :request_id FOR UPDATE"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .first()
            )
            if request is None:
                raise AppError(404, "request_not_found", "Garden request not found")
            if (
                request["status"] != "implements_installed"
                or request["property_id"] != expected_property_id
            ):
                raise AppError(
                    409,
                    "request_changed",
                    "Complete installation before allocating crops. Refresh and try again.",
                )

            report = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, recommended_crops FROM public.inspection_reports "
                            "WHERE id = :report_id AND garden_id = :property_id "
                            "AND assessment_status = 'approved' FOR UPDATE"
                        ),
                        {"report_id": approved_report_id, "property_id": expected_property_id},
                    )
                )
                .mappings()
                .first()
            )
            if report is None:
                raise AppError(
                    409,
                    "inspection_approval_required",
                    "An approved, viable inspector assessment is required before crop allocation.",
                )
            recommended_crops = set(report["recommended_crops"] or [])
            unsupported_crops = [
                crop["name"] for crop in crop_rows if crop["name"] not in recommended_crops
            ]
            if unsupported_crops:
                raise AppError(
                    422,
                    "crop_not_recommended",
                    "Allocate crops recommended by the approved site assessment.",
                    {"unsupportedCrops": unsupported_crops},
                )

            property_result = await connection.execute(
                text(
                    "UPDATE public.properties SET label = :label, address = :address, "
                    "city = :city, lat = :lat, lng = :lng, "
                    "available_space_m2 = :available_space_m2, "
                    "sunlight_hours = :sunlight_hours, notes = :notes "
                    "WHERE id = :property_id AND owner_id = :owner_id RETURNING id"
                ),
                {
                    **property_payload,
                    "property_id": expected_property_id,
                    "owner_id": request["owner_id"],
                },
            )
            if not property_result.mappings().first():
                raise AppError(409, "property_changed", "The linked property could not be updated.")

            installation = (
                (
                    await connection.execute(
                        text(
                            "SELECT id FROM public.installations "
                            "WHERE property_id = :property_id AND status = 'active' "
                            "AND installed_at IS NOT NULL ORDER BY created_at ASC "
                            "LIMIT 1 FOR UPDATE"
                        ),
                        {"property_id": expected_property_id},
                    )
                )
                .mappings()
                .first()
            )
            if installation is None:
                raise AppError(
                    409, "installation_not_complete", "No completed installation is recorded."
                )

            existing_batches = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, crop_id FROM public.crop_batches "
                            "WHERE installation_id = :installation_id FOR UPDATE"
                        ),
                        {"installation_id": installation["id"]},
                    )
                )
                .mappings()
                .all()
            )
            existing_crop_ids = {str(batch["crop_id"]) for batch in existing_batches}
            batch_ids = [str(batch["id"]) for batch in existing_batches]
            for crop in crop_rows:
                if str(crop["id"]) in existing_crop_ids:
                    continue
                inserted = (
                    (
                        await connection.execute(
                            text(
                                "INSERT INTO public.crop_batches "
                                "(owner_id, installation_id, crop_id, units, "
                                "expected_yield_kg, status) VALUES "
                                "(:owner_id, :installation_id, :crop_id, 1, "
                                ":expected_yield_kg, 'planned') RETURNING id"
                            ),
                            {
                                "owner_id": request["owner_id"],
                                "installation_id": installation["id"],
                                "crop_id": crop["id"],
                                "expected_yield_kg": crop.get("est_yield_kg_per_unit") or 0,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if inserted is None:
                    raise AppError(409, "crop_allocation_failed", "Could not allocate a crop.")
                existing_crop_ids.add(str(crop["id"]))
                batch_ids.append(str(inserted["id"]))

            request_details = request["details"]
            merged_details = {
                **(request_details if isinstance(request_details, dict) else {}),
                **detail_updates,
            }
            if not merged_details.get("requestedPlants"):
                merged_details["requestedPlants"] = merged_details.get("plants") or []
            updated_request = (
                (
                    await connection.execute(
                        text(
                            "UPDATE public.garden_requests SET property_id = :property_id, "
                            "status = 'seeds', reviewed_by = :actor_id, reviewed_at = now(), "
                            "admin_notes = :admin_notes, details = CAST(:details AS jsonb) "
                            "WHERE id = :request_id AND status = 'implements_installed' "
                            "RETURNING *"
                        ),
                        {
                            "property_id": expected_property_id,
                            "actor_id": actor_id,
                            "admin_notes": admin_notes,
                            "details": json.dumps(merged_details),
                            "request_id": request_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if updated_request is None:
                raise AppError(
                    409,
                    "request_changed",
                    "The request changed while crop allocation was being recorded.",
                )

            activity_rows = (
                {
                    "activity_type": "inspection",
                    "title": "Crop allocation recorded",
                    "details": {
                        "meta": detail_updates.get("inspectionNotes"),
                        "approvedReportId": str(report["id"]),
                    },
                },
                {
                    "activity_type": "planting",
                    "title": "Crops allocated",
                    "details": {"allocated_plants": detail_updates.get("allocatedPlants", [])},
                },
            )
            for activity in activity_rows:
                await connection.execute(
                    text(
                        "INSERT INTO public.garden_activity_logs "
                        "(owner_id, property_id, installation_id, activity_type, title, details) "
                        "VALUES (:owner_id, :property_id, :installation_id, :activity_type, "
                        ":title, CAST(:details AS jsonb))"
                    ),
                    {
                        "owner_id": request["owner_id"],
                        "property_id": expected_property_id,
                        "installation_id": installation["id"],
                        **activity,
                        "details": json.dumps(activity["details"]),
                    },
                )

            stages = (
                (
                    await connection.execute(
                        text(
                            "SELECT stage.id, stage.stage_key, stage.evidence, stage.started_at "
                            "FROM public.workflow_stages AS stage "
                            "INNER JOIN public.operational_workflows AS workflow "
                            "ON workflow.id = stage.workflow_id "
                            "WHERE workflow.garden_request_id = :request_id "
                            "AND stage.stage_key IN ('crop_allocation', 'maintenance_tasks') "
                            "FOR UPDATE OF stage"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .all()
            )
            stage_by_key = {stage["stage_key"]: stage for stage in stages}
            for stage_key in ("crop_allocation", "maintenance_tasks"):
                if stage_key not in stage_by_key:
                    raise AppError(
                        409,
                        "workflow_stage_missing",
                        f"Workflow stage {stage_key} is missing.",
                    )

            crop_stage = stage_by_key["crop_allocation"]
            crop_evidence = {
                **(crop_stage["evidence"] if isinstance(crop_stage["evidence"], dict) else {}),
                "installation_id": str(installation["id"]),
                "crop_batch_ids": batch_ids,
                "recommended_crops": sorted(recommended_crops),
            }
            maintenance_stage = stage_by_key["maintenance_tasks"]
            maintenance_evidence = (
                maintenance_stage["evidence"]
                if isinstance(maintenance_stage["evidence"], dict)
                else {}
            )
            for stage, status, evidence, action in (
                (crop_stage, "completed", crop_evidence, None),
                (
                    maintenance_stage,
                    "ready",
                    maintenance_evidence,
                    "Plant allocated crops and record the planting date.",
                ),
            ):
                updated_stage = await connection.execute(
                    text(
                        "UPDATE public.workflow_stages SET status = :status, "
                        "owner_user_id = :actor_id, evidence = CAST(:evidence AS jsonb), "
                        "started_at = COALESCE(started_at, now()), "
                        "completed_at = CASE WHEN :status = 'completed' "
                        "THEN now() ELSE completed_at END, "
                        "next_action = COALESCE(CAST(:next_action AS text), next_action), "
                        "updated_at = now() "
                        "WHERE id = :stage_id RETURNING id"
                    ),
                    {
                        "status": status,
                        "actor_id": actor_id,
                        "evidence": json.dumps(evidence),
                        "next_action": action,
                        "stage_id": stage["id"],
                    },
                )
                if not updated_stage.mappings().first():
                    raise AppError(
                        409,
                        "workflow_stage_update_failed",
                        f"Could not advance {stage['stage_key']}.",
                    )

            return {
                "ok": True,
                "requestId": str(request_id),
                "propertyId": str(expected_property_id),
                "installationId": str(installation["id"]),
                "allocatedPlants": detail_updates.get("allocatedPlants", []),
                "matchedPlants": [crop["name"] for crop in crop_rows],
                "status": "seeds",
            }
