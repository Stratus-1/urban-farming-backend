from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.infrastructure.postgres_gateway import (
    bind_value,
    build_filters,
    coerce_column_value,
    quote_identifier,
)


def test_build_filters_parameterizes_values() -> None:
    where_sql, parameters = build_filters(
        {
            "owner_id": "8cda0b73-f149-45f9-a75b-f74be25fb174",
            "status": ["pending", "in_progress"],
            "deleted_at": None,
        }
    )

    assert '"owner_id" = :filter_0' in where_sql
    assert '"status" IN (:filter_1_0, :filter_1_1)' in where_sql
    assert '"deleted_at" IS NULL' in where_sql
    assert parameters["filter_1_0"] == "pending"


def test_quote_identifier_rejects_injection() -> None:
    try:
        quote_identifier('properties; DROP TABLE "properties"')
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe SQL identifiers must be rejected")


def test_build_filters_coerces_iso_timestamps_for_asyncpg() -> None:
    where_sql, parameters = build_filters(
        {
            "scheduled_at": "gte.2026-07-12T21:15:25.899Z",
            "created_at": "2026-07-12T23:15:25+02:00",
        }
    )

    assert '"scheduled_at" >= :filter_0' in where_sql
    assert parameters["filter_0"] == datetime(2026, 7, 12, 21, 15, 25, 899000, tzinfo=UTC)
    assert parameters["filter_1"] == datetime.fromisoformat("2026-07-12T23:15:25+02:00")


def test_bind_value_serializes_json_objects_for_asyncpg() -> None:
    placeholder, value = bind_value(
        "details",
        {"trackingState": "requested", "plants": ["Lettuce", "Basil"]},
    )

    assert placeholder == "CAST(:details AS JSONB)"
    assert value == '{"trackingState": "requested", "plants": ["Lettuce", "Basil"]}'


def test_coerce_column_value_converts_json_temporal_strings_for_asyncpg() -> None:
    assert coerce_column_value("2026-07-14", "date") == date(2026, 7, 14)
    assert coerce_column_value("2026-07-14T07:00:00.000Z", "timestamp with time zone") == datetime(
        2026, 7, 14, 7, tzinfo=UTC
    )
    assert coerce_column_value("07:30:00", "time without time zone") == time(7, 30)


def test_coerce_column_value_preserves_text_even_when_it_looks_like_a_date() -> None:
    assert coerce_column_value("2026-07-14", "text") == "2026-07-14"


def test_coerce_column_value_rejects_invalid_temporal_values() -> None:
    with pytest.raises(AppError) as raised:
        coerce_column_value("not-a-date", "date")

    assert raised.value.status_code == 422
    assert raised.value.code == "invalid_temporal_value"


class _MappingsResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        return self.row


class _InspectionConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.report = None
        self.checklist_exists = False

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM public.inspection_assignments" in sql:
            return _MappingsResult(
                {
                    "id": UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
                    "inspector_id": UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
                    "garden_id": UUID("06ac42e0-c673-4412-9660-272de2f9b9cb"),
                    "status": "pending",
                    "started_at": None,
                }
            )
        if "FROM public.inspection_reports" in sql:
            return _MappingsResult(self.report)
        if "INSERT INTO public.inspection_reports" in sql:
            self.report = {
                "id": UUID("b76b535f-6b92-4cb8-9b5e-cf9a1c4ab579"),
                "assignment_id": UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
                "inspector_id": UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
                "garden_id": UUID("06ac42e0-c673-4412-9660-272de2f9b9cb"),
                "overall_status": "pending",
            }
            return _MappingsResult(self.report)
        return _MappingsResult()

    async def scalar(self, _statement, _parameters=None):
        return self.checklist_exists


class _InspectionTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, _type, _value, _traceback):
        return False


class _InspectionEngine:
    def __init__(self, connection) -> None:
        self.connection = connection

    def begin(self):
        return _InspectionTransaction(self.connection)


@pytest.mark.asyncio
async def test_postgres_start_inspection_report_locks_assignment_and_seeds_checklist() -> None:
    from app.infrastructure.postgres_gateway import PostgresGateway

    gateway = PostgresGateway.__new__(PostgresGateway)
    connection = _InspectionConnection()
    gateway.engine = _InspectionEngine(connection)

    report = await gateway.start_inspection_report(
        assignment_id=UUID("226b3f34-1e69-47b0-a691-1932d08001bf"),
        inspector_id=UUID("4caa21df-b050-43af-8f99-9fdf0627aeb0"),
        gps_lat=-34.0,
        gps_lng=18.5,
        checklist_template=(
            ("Garden condition", "Full garden view", True, 1),
            ("Crop health", "Leaf and growth check", True, 2),
        ),
        token="inspector-token",
    )

    assignment_lock = next(sql for sql, _params in connection.statements if "FOR UPDATE" in sql)
    checklist_seed = next(
        params
        for sql, params in connection.statements
        if "INSERT INTO public.inspection_checklist_items" in sql
    )
    assert report["overall_status"] == "pending"
    assert "inspector_id = :inspector_id" in assignment_lock
    assert len(checklist_seed) == 2
    assert checklist_seed[0]["category"] == "Garden condition"
    assert checklist_seed[0]["requires_photo"] is True
