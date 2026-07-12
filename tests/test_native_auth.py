from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _native_settings() -> Settings:
    return Settings(
        environment="test",
        auth_mode="native",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@127.0.0.1:1/test",
        storage_backend="gcs",
        gcs_bucket="test-bucket",
        jwt_secret="test-secret",
    )


class FakeAuthStore:
    def __init__(self) -> None:
        self.users: dict[UUID, dict[str, Any]] = {}
        self.roles: dict[UUID, set[str]] = {}
        self.refresh_tokens: dict[UUID, dict[str, Any]] = {}

    async def create_user(
        self,
        *,
        email: str,
        password_hash: str | None,
        user_metadata: dict[str, Any],
        app_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.core.errors import AppError

        if any(u["email"] == email.lower() for u in self.users.values()):
            raise AppError(409, "email_exists", "An account with this email already exists")
        user_id = uuid4()
        row = {
            "id": user_id,
            "email": email.lower(),
            "encrypted_password": password_hash,
            "raw_user_meta_data": user_metadata,
            "created_at": datetime.now(UTC),
        }
        self.users[user_id] = row
        return dict(row)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        for row in self.users.values():
            if row["email"] == email.lower():
                return dict(row)
        return None

    async def get_user_by_id(self, user_id: UUID) -> dict[str, Any] | None:
        row = self.users.get(user_id)
        return dict(row) if row else None

    async def set_password(self, user_id: UUID, password_hash: str) -> None:
        self.users[user_id]["encrypted_password"] = password_hash

    async def touch_last_sign_in(self, user_id: UUID) -> None:
        pass

    async def user_roles(self, user_id: UUID) -> list[str]:
        return sorted(self.roles.get(user_id, set()))

    async def ensure_provisioned(self, user_id: UUID, *, full_name: str | None, role: str) -> None:
        self.roles.setdefault(user_id, set()).add(role)

    async def store_refresh_token(
        self, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        self.refresh_tokens[token_id] = {"user_id": user_id, "revoked": False}

    async def is_refresh_token_active(self, token_id: UUID) -> bool:
        entry = self.refresh_tokens.get(token_id)
        return bool(entry) and not entry["revoked"]

    async def revoke_refresh_token(self, token_id: UUID) -> None:
        if token_id in self.refresh_tokens:
            self.refresh_tokens[token_id]["revoked"] = True

    async def revoke_all_refresh_tokens(self, user_id: UUID) -> None:
        for entry in self.refresh_tokens.values():
            if entry["user_id"] == user_id:
                entry["revoked"] = True


class FakeGateway:
    def __init__(self, store: FakeAuthStore) -> None:
        self.store = store

    async def select(self, table: str, **kwargs: Any) -> list[dict[str, Any]]:
        assert table == "user_roles"
        user_id = kwargs.get("filters", {}).get("user_id")
        return [{"role": role} for role in await self.store.user_roles(user_id)]


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: Any) -> bool:
        self.sent.append(message)
        return True


def _client_with_fakes() -> tuple[TestClient, FakeAuthStore, FakeEmail]:
    app = create_app(_native_settings())
    client = TestClient(app)
    client.__enter__()
    store = FakeAuthStore()
    email = FakeEmail()
    app.state.auth_store = store
    app.state.gateway = FakeGateway(store)
    app.state.email = email
    return client, store, email


SIGNUP = {
    "email": "grower@example.com",
    "password": "secret123",
    "full_name": "Test Grower",
    "role": "grower",
}


def test_native_signup_login_me_flow() -> None:
    client, _store, _email = _client_with_fakes()
    try:
        signup = client.post("/api/v1/auth/signup", json=SIGNUP)
        assert signup.status_code == 201
        body = signup.json()
        assert body["roles"] == ["grower"]
        assert body["confirmation_required"] is False
        assert body["session"]["access_token"]

        duplicate = client.post("/api/v1/auth/signup", json=SIGNUP)
        assert duplicate.status_code == 409

        bad = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": "wrong-password"},
        )
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "invalid_credentials"

        login = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
        )
        assert login.status_code == 200
        session = login.json()["session"]

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == SIGNUP["email"]
        assert me.json()["roles"] == ["grower"]
    finally:
        client.__exit__(None, None, None)


def test_native_signup_preserves_json_metadata() -> None:
    client, store, _email = _client_with_fakes()
    try:
        response = client.post("/api/v1/auth/signup", json=SIGNUP)
        assert response.status_code == 201
        user = next(iter(store.users.values()))
        assert user["raw_user_meta_data"] == {
            "full_name": SIGNUP["full_name"],
            "role": SIGNUP["role"],
        }
    finally:
        client.__exit__(None, None, None)


def test_native_refresh_rotation_and_logout() -> None:
    client, _store, _email = _client_with_fakes()
    try:
        client.post("/api/v1/auth/signup", json=SIGNUP)
        login = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
        )
        session = login.json()["session"]

        refreshed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert refreshed.status_code == 200
        new_session = refreshed.json()["session"]
        assert new_session["refresh_token"] != session["refresh_token"]

        replayed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert replayed.status_code == 401

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_session['access_token']}"},
        )
        assert logout.status_code == 200

        after_logout = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_session["refresh_token"]}
        )
        assert after_logout.status_code == 401
    finally:
        client.__exit__(None, None, None)


def test_native_password_reset_and_update() -> None:
    client, _store, email = _client_with_fakes()
    try:
        client.post("/api/v1/auth/signup", json=SIGNUP)

        unknown = client.post("/api/v1/auth/password-reset", json={"email": "nobody@example.com"})
        assert unknown.status_code == 200
        assert not email.sent

        reset = client.post(
            "/api/v1/auth/password-reset",
            json={"email": SIGNUP["email"], "redirect_to": "https://app.example.com/reset"},
        )
        assert reset.status_code == 200
        assert len(email.sent) == 1
        assert "token=" in email.sent[0].text

        login = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
        )
        access_token = login.json()["session"]["access_token"]
        updated = client.put(
            "/api/v1/auth/password",
            json={"password": "new-secret-456"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert updated.status_code == 200

        old_password = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
        )
        assert old_password.status_code == 401
        new_password = client.post(
            "/api/v1/auth/login",
            json={"email": SIGNUP["email"], "password": "new-secret-456"},
        )
        assert new_password.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_google_sign_in_creates_user(monkeypatch) -> None:
    client, _store, _email = _client_with_fakes()
    try:

        async def fake_claims(settings, id_token: str) -> dict:
            return {
                "email": "google-user@example.com",
                "email_verified": True,
                "name": "Google User",
                "sub": "google-sub-123",
            }

        monkeypatch.setattr("app.routers.auth._google_claims", fake_claims)
        response = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == "google-user@example.com"
        assert body["roles"] == ["grower"]
        assert body["session"]["access_token"]

        again = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})
        assert again.status_code == 200
        assert again.json()["user"]["id"] == body["user"]["id"]
    finally:
        client.__exit__(None, None, None)


def test_native_mode_requires_jwt_secret() -> None:
    settings = _native_settings()
    settings.jwt_secret = None
    try:
        settings.validate_runtime()
    except RuntimeError as error:
        assert "JWT_SECRET" in str(error)
    else:
        raise AssertionError("Native mode must require JWT_SECRET")
