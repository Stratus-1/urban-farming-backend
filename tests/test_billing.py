import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

TEST_USER_ID = str(uuid4())


class FakeGateway:
    def __init__(self) -> None:
        self.user_settings: dict[str, dict[str, Any]] = {}

    async def select(self, table: str, **kwargs: Any) -> dict[str, Any] | None:
        assert table == "user_settings"
        filters = kwargs.get("filters") or {}
        user_id = str(filters.get("user_id"))
        return self.user_settings.get(user_id)

    async def insert(
        self,
        table: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        assert table == "user_settings"
        user_id = str(payload["user_id"])
        current = self.user_settings.get(user_id, {})
        merged = {**current, **payload}
        self.user_settings[user_id] = merged
        return [merged]


class FakeHttpClient:
    async def request(self, method: str, url: str, **kwargs: Any):
        class Response:
            def __init__(self, body: dict[str, Any]) -> None:
                self._body = body
                self.is_error = False
                self.status_code = 200
                self.headers = {"content-type": "application/json"}

            def json(self) -> dict[str, Any]:
                return self._body

        if url.endswith("/checkout/sessions"):
            return Response({"url": "https://checkout.stripe.test/session_123"})
        if url.endswith("/billing_portal/sessions"):
            return Response({"url": "https://billing.stripe.test/portal_123"})
        return Response({})


def _settings() -> Settings:
    return Settings(
        environment="test",
        auth_mode="development",
        data_backend="postgres",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        storage_backend="gcs",
        gcs_bucket="test-bucket",
        stripe_secret_key="sk_test_123",
        stripe_publishable_key="pk_test_123",
        stripe_webhook_secret="whsec_test_123",
        stripe_price_premium_monthly="price_123",
    )


def _client() -> tuple[TestClient, FakeGateway]:
    app = create_app(_settings())
    client = TestClient(app)
    client.__enter__()
    gateway = FakeGateway()
    app.state.gateway = gateway
    app.state.http = FakeHttpClient()
    return client, gateway


def _headers() -> dict[str, str]:
    return {"X-User-Id": TEST_USER_ID, "X-User-Role": "grower"}


def test_billing_overview_defaults_to_inactive() -> None:
    client, _gateway = _client()
    try:
        response = client.get("/api/v1/billing", headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["subscription"]["active"] is False
        assert body["plans"][0]["code"] == "premium-monthly"
    finally:
        client.__exit__(None, None, None)


def test_checkout_and_portal_sessions_use_stripe() -> None:
    client, gateway = _client()
    gateway.user_settings[TEST_USER_ID] = {
        "user_id": TEST_USER_ID,
        "billing_customer_id": "cus_123",
        "billing_subscription_status": "active",
    }
    try:
        checkout = client.post("/api/v1/billing/checkout-session", headers=_headers())
        assert checkout.status_code == 200
        assert checkout.json()["checkout_url"].startswith("https://checkout.stripe.test/")

        portal = client.post("/api/v1/billing/portal-session", headers=_headers())
        assert portal.status_code == 200
        assert portal.json()["portal_url"].startswith("https://billing.stripe.test/")
    finally:
        client.__exit__(None, None, None)


def test_webhook_updates_subscription_state() -> None:
    client, gateway = _client()
    payload = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "current_period_end": 1786665600,
                "cancel_at_period_end": False,
                "metadata": {"user_id": TEST_USER_ID},
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    timestamp = "1786600000"
    digest = hmac.new(
        _settings().stripe_webhook_secret.encode("utf-8"),
        f"{timestamp}.{raw.decode('utf-8')}".encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        response = client.post(
            "/api/v1/billing/webhooks",
            headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
            content=raw,
        )
        assert response.status_code == 200
        assert gateway.user_settings[TEST_USER_ID]["billing_subscription_id"] == "sub_123"
        assert gateway.user_settings[TEST_USER_ID]["billing_subscription_status"] == "active"
    finally:
        client.__exit__(None, None, None)
