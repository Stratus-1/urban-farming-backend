from datetime import UTC, datetime

from app.infrastructure.postgres_gateway import build_filters, quote_identifier


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
