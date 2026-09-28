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
    assert "/api/v1/inspections/reports/{report_id}/assessment" in paths
    assert "/api/v1/inspections/reports/{report_id}/submit-for-approval" in paths
    assert "/api/v1/admin/dashboard" in paths
    assert "/api/v1/orders" in paths
    assert "/api/v1/assessment-leads" in paths
    assert "/api/v1/admin/assessment-leads" in paths
    assert "/api/v1/admin/assessment-leads/{lead_id}" in paths
    assert "/api/v1/admin/assessment-leads/{lead_id}/convert" in paths
    assert "/api/v1/mobile/push-tokens" in paths
    assert "/api/v1/mobile/notifications/send" in paths


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


def test_production_rejects_loopback_cors_origins() -> None:
    settings = Settings(
        environment="production",
        auth_mode="native",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        jwt_secret="test-secret",
        app_base_url="https://urban.example.com",
        allowed_origins="https://urban.example.com,http://localhost:5173",
    )

    try:
        settings.validate_runtime()
    except RuntimeError as error:
        assert "public HTTPS origins" in str(error)
    else:
        raise AssertionError("Production must reject loopback CORS origins")


def test_production_requires_app_base_url_to_be_an_allowed_https_origin() -> None:
    settings = Settings(
        environment="production",
        auth_mode="native",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        jwt_secret="test-secret",
        app_base_url="http://urban.example.com",
        allowed_origins="https://urban.example.com",
    )

    try:
        settings.validate_runtime()
    except RuntimeError as error:
        assert "APP_BASE_URL origin" in str(error)
    else:
        raise AssertionError("Production APP_BASE_URL must use an allowed HTTPS origin")


def test_production_rejects_https_localhost_cors_origin() -> None:
    settings = Settings(
        environment="production",
        auth_mode="native",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        jwt_secret="test-secret",
        app_base_url="https://urban.example.com",
        allowed_origins="https://urban.example.com,https://localhost",
    )

    try:
        settings.validate_runtime()
    except RuntimeError as error:
        assert "public HTTPS origins" in str(error)
    else:
        raise AssertionError("Production must reject a localhost origin even over HTTPS")
