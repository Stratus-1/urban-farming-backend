from datetime import UTC, date, datetime, time

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
    assert coerce_column_value(
        "2026-07-14T07:00:00.000Z", "timestamp with time zone"
    ) == datetime(2026, 7, 14, 7, tzinfo=UTC)
    assert coerce_column_value("07:30:00", "time without time zone") == time(7, 30)


def test_coerce_column_value_preserves_text_even_when_it_looks_like_a_date() -> None:
    assert coerce_column_value("2026-07-14", "text") == "2026-07-14"


def test_coerce_column_value_rejects_invalid_temporal_values() -> None:
    with pytest.raises(AppError) as raised:
        coerce_column_value("not-a-date", "date")

    assert raised.value.status_code == 422
    assert raised.value.code == "invalid_temporal_value"
