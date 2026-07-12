from app.core.config import Settings
from app.main import create_app


def test_openapi_exposes_migrated_domain_contracts() -> None:
    app = create_app(
        Settings(
            environment="test",
            auth_mode="development",
            data_backend="postgres",
            database_url="postgresql+asyncpg://test:test@localhost/test",
            storage_backend="gcs",
            gcs_bucket="test-bucket",
        )
    )

    paths = app.openapi()["paths"]

    assert "/api/v1/gardens/overview" in paths
    assert "/api/v1/garden-requests/{request_id}/allocation" in paths
    assert "/api/v1/inspections/reports/{report_id}/photos" in paths
    assert "/api/v1/admin/dashboard" in paths
    assert "/api/v1/orders" in paths


def test_development_auth_is_blocked_in_production() -> None:
    settings = Settings(
        environment="production",
        auth_mode="development",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        storage_backend="gcs",
        gcs_bucket="test-bucket",
    )

    try:
        settings.validate_runtime()
    except RuntimeError as error:
        assert "Development authentication" in str(error)
    else:
        raise AssertionError("Production must reject development authentication")


def test_allowed_origins_accepts_comma_separated_environment_value() -> None:
    settings = Settings(allowed_origins="http://127.0.0.1:8081,https://urban.example.com")

    assert settings.allowed_origins == [
        "http://127.0.0.1:8081",
        "https://urban.example.com",
    ]
