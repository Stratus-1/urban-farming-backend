from typing import Any

import httpx

from app.core.errors import AppError
from app.infrastructure.data_gateway import ensure_rpc_allowed, ensure_table_allowed


class SupabaseGateway:
    """PostgREST compatibility adapter used during the zero-downtime cutover."""

    def __init__(
        self,
        *,
        url: str,
        anon_key: str,
        service_role_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.service_role_key = service_role_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _headers(
        self,
        token: str | None,
        *,
        prefer: str | None = None,
        admin: bool = False,
    ) -> dict[str, str]:
        api_key = self.service_role_key if admin and self.service_role_key else self.anon_key
        bearer = api_key if admin and self.service_role_key else token or self.anon_key
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, f"{self.url}{path}", **kwargs)
        except httpx.TimeoutException as error:
            raise AppError(504, "upstream_timeout", "The data service timed out") from error
        except httpx.HTTPError as error:
            raise AppError(
                502, "upstream_unavailable", "The data service is unavailable"
            ) from error

        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {"message": response.text[:500]}
            status = 404 if response.status_code == 406 else response.status_code
            raise AppError(
                status,
                str(body.get("code") or "supabase_error"),
                str(body.get("message") or "Supabase request failed"),
                body.get("details") or body.get("hint"),
            )
        return response

    async def ping(self) -> bool:
        response = await self._request(
            "GET",
            "/rest/v1/crops",
            headers=self._headers(None),
            params={"select": "id", "limit": "1"},
        )
        return response.status_code == 200

    @staticmethod
    def _params(
        columns: str,
        filters: dict[str, Any] | None,
        order: str | None,
        limit: int | None,
    ) -> dict[str, str]:
        params = {"select": columns}
        for key, value in (filters or {}).items():
            if value is None:
                params[key] = "is.null"
            elif isinstance(value, (list, tuple, set)):
                params[key] = f"in.({','.join(str(item) for item in value)})"
            elif isinstance(value, str) and value.startswith(
                ("eq.", "neq.", "gte.", "lte.", "gt.", "lt.", "is.", "in.", "ilike.")
            ):
                params[key] = value
            else:
                params[key] = f"eq.{value}"
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        return params

    async def select(
        self,
        table: str,
        *,
        token: str | None = None,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        single: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        ensure_table_allowed(table)
        response = await self._request(
            "GET",
            f"/rest/v1/{table}",
            headers=self._headers(token),
            params=self._params(columns, filters, order, limit),
        )
        data = response.json()
        return (data[0] if data else None) if single else data

    async def insert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        token: str | None = None,
        upsert: bool = False,
        on_conflict: str | None = None,
    ) -> list[dict[str, Any]]:
        ensure_table_allowed(table)
        params = {"on_conflict": on_conflict} if on_conflict else None
        prefer = "return=representation"
        if upsert:
            prefer += ",resolution=merge-duplicates"
        response = await self._request(
            "POST",
            f"/rest/v1/{table}",
            headers=self._headers(token, prefer=prefer),
            params=params,
            json=payload,
        )
        return response.json()

    async def update(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        filters: dict[str, Any],
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        ensure_table_allowed(table)
        response = await self._request(
            "PATCH",
            f"/rest/v1/{table}",
            headers=self._headers(token, prefer="return=representation"),
            params=self._params("*", filters, None, None),
            json=payload,
        )
        return response.json()

    async def delete(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        token: str | None = None,
    ) -> None:
        ensure_table_allowed(table)
        await self._request(
            "DELETE",
            f"/rest/v1/{table}",
            headers=self._headers(token),
            params=self._params("*", filters, None, None),
        )

    async def rpc(self, name: str, payload: dict[str, Any], *, token: str | None = None) -> Any:
        ensure_rpc_allowed(name)
        response = await self._request(
            "POST",
            f"/rest/v1/rpc/{name}",
            headers=self._headers(token),
            json=payload,
        )
        return response.json()

    async def get_auth_user(self, token: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "/auth/v1/user",
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {token}",
            },
        )
        return response.json()

    async def upload_inspection_photo(
        self, path: str, content: bytes, content_type: str, token: str
    ) -> str:
        response = await self._request(
            "POST",
            f"/storage/v1/object/inspection-photos/{path}",
            headers={
                **self._headers(token),
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            content=content,
        )
        response.json()
        return f"{self.url}/storage/v1/object/public/inspection-photos/{path}"
