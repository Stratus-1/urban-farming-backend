from uuid import UUID

import pytest

from app.core.security import CurrentUser
from app.routers.commerce import list_orders


USER_ID = UUID("8cda0b73-f149-45f9-a75b-f74be25fb174")


class OrdersGateway:
    def __init__(self) -> None:
        self.filters = None

    async def select(self, table: str, **kwargs):
        self.filters = kwargs["filters"]
        return [{"id": "order-a", "buyer_id": str(USER_ID)}]


@pytest.mark.asyncio
async def test_buyer_orders_are_scoped_to_the_authenticated_buyer() -> None:
    gateway = OrdersGateway()
    user = CurrentUser(id=USER_ID, roles={"buyer"}, access_token="buyer-token")

    result = await list_orders(gateway, user)

    assert gateway.filters == {"buyer_id": USER_ID}
    assert result == {"items": [{"id": "order-a", "buyer_id": str(USER_ID)}], "count": 1}
