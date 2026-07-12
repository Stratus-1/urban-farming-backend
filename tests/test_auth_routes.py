import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import Settings
from app.main import create_app

SUPABASE_URL = "https://test-project.supabase.co"
USER_ID = "8b7d3a52-1c2e-4f66-9a10-3d9f1b2c4e5d"


def _supabase_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "auth_mode": "supabase",
        "data_backend": "supabase",
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": "anon-key",
        "storage_backend": "supabase",
        **overrides,
    }
    return Settings(**values)


def test_openapi_exposes_auth_endpoints() -> None:
    app = create_app(_supabase_settings())

    paths = app.openapi()["paths"]

    assert "/api/v1/auth/signup" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/auth/password-reset" in paths
    assert "/api/v1/auth/password" in paths
    assert "/api/v1/auth/me" in paths


@respx.mock
def test_login_returns_session_and_roles() -> None:
    respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "access-token",
                "token_type": "bearer",
                "expires_in": 3600,
                "refresh_token": "refresh-token",
                "user": {"id": USER_ID, "email": "grower@example.com"},
            },
        )
    )
    respx.get(f"{SUPABASE_URL}/rest/v1/user_roles").mock(
        return_value=Response(200, json=[{"role": "grower"}])
    )

    with TestClient(create_app(_supabase_settings())) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "grower@example.com", "password": "secret123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["access_token"] == "access-token"
    assert body["user"]["email"] == "grower@example.com"
    assert body["roles"] == ["grower"]


@respx.mock
def test_login_passes_through_gotrue_error() -> None:
    respx.post(f"{SUPABASE_URL}/auth/v1/token").mock(
        return_value=Response(
            400,
            json={"error_code": "invalid_credentials", "msg": "Invalid login credentials"},
        )
    )

    with TestClient(create_app(_supabase_settings())) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "grower@example.com", "password": "wrong"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_credentials"


@respx.mock
def test_signup_reports_confirmation_required() -> None:
    respx.post(f"{SUPABASE_URL}/auth/v1/signup").mock(
        return_value=Response(200, json={"id": USER_ID, "email": "new@example.com"})
    )

    with TestClient(create_app(_supabase_settings())) as client:
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "new@example.com",
                "password": "secret123",
                "full_name": "New Grower",
                "role": "grower",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session"] is None
    assert body["confirmation_required"] is True
    assert body["roles"] == ["grower"]
    assert body["user"]["email"] == "new@example.com"


def test_signup_rejects_admin_role() -> None:
    with TestClient(create_app(_supabase_settings())) as client:
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "sneaky@example.com",
                "password": "secret123",
                "full_name": "Sneaky",
                "role": "admin",
            },
        )

    assert response.status_code == 422


def test_auth_endpoints_require_supabase_mode() -> None:
    settings = _supabase_settings(
        auth_mode="oidc",
        oidc_issuer="https://issuer.example.com",
        oidc_audience="urban-farming",
        oidc_jwks_url="https://issuer.example.com/jwks",
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "grower@example.com", "password": "secret123"},
        )

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "unsupported_auth_mode"
