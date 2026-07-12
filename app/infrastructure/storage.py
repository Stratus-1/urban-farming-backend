import asyncio
from typing import Protocol

from google.cloud import storage

from app.core.errors import AppError
from app.infrastructure.supabase_gateway import SupabaseGateway


class StorageGateway(Protocol):
    async def upload(
        self, path: str, content: bytes, content_type: str, access_token: str
    ) -> str: ...


class SupabaseStorageGateway:
    def __init__(self, gateway: SupabaseGateway) -> None:
        self.gateway = gateway

    async def upload(self, path: str, content: bytes, content_type: str, access_token: str) -> str:
        return await self.gateway.upload_inspection_photo(path, content, content_type, access_token)


class GCSStorageGateway:
    def __init__(self, bucket_name: str, project_id: str | None = None) -> None:
        self.bucket_name = bucket_name
        self.project_id = project_id
        # Created lazily so the API can boot without GCP credentials (e.g. local dev).
        self._client: storage.Client | None = None

    def _bucket(self) -> "storage.Bucket":
        if self._client is None:
            self._client = storage.Client(project=self.project_id)
        return self._client.bucket(self.bucket_name)

    async def upload(self, path: str, content: bytes, content_type: str, access_token: str) -> str:
        del access_token

        def do_upload() -> None:
            blob = self._bucket().blob(path)
            blob.upload_from_string(content, content_type=content_type)

        try:
            await asyncio.to_thread(do_upload)
        except Exception as error:
            raise AppError(502, "storage_error", "Could not upload the inspection photo") from error
        return f"gs://{self.bucket.name}/{path}"
