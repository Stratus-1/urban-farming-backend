import httpx
import pytest

from app.infrastructure.supabase_gateway import SupabaseGateway


@pytest.mark.asyncio
async def test_select_forwards_user_token_and_rls_filters() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json=[{"id": "garden-1"}])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = SupabaseGateway(
        url="https://example.supabase.co",
        anon_key="anon-key",
        client=client,
    )

    rows = await gateway.select(
        "properties",
        token="user-token",
        filters={"owner_id": "user-1"},
        order="created_at.desc",
    )

    assert rows == [{"id": "garden-1"}]
    assert captured_request is not None
    assert captured_request.headers["authorization"] == "Bearer user-token"
    assert captured_request.url.params["owner_id"] == "eq.user-1"
    await client.aclose()
