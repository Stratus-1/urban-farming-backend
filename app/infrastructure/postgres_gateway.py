import json
import re
from datetime import date, datetime, time
from typing import Any

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

ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

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

    async def insert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        token: str | None = None,
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

    async def rpc(self, name: str, payload: dict[str, Any], *, token: str | None = None) -> Any:
        ensure_rpc_allowed(name)
        arguments = ", ".join(f"{quote_identifier(key)} => :{key}" for key in payload)
        async with self.engine.connect() as connection:
            await self._set_identity(connection, token)
            result = await connection.execute(
                text(f"SELECT * FROM public.{quote_identifier(name)}({arguments})"), payload
            )
            return [dict(row) for row in result.mappings().all()]
