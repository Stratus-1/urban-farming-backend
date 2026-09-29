import pytest

from app.infrastructure import storage as storage_module
from app.infrastructure.storage import GCSStorageGateway


class FakeBlob:
    def __init__(self) -> None:
        self.upload: tuple[bytes, str] | None = None

    def upload_from_string(self, content: bytes, *, content_type: str) -> None:
        self.upload = (content, content_type)


class FakeBucket:
    def __init__(self) -> None:
        self.blob_instance = FakeBlob()

    def blob(self, path: str) -> FakeBlob:
        assert path == "inspector/report/photo.jpg"
        return self.blob_instance


class FakeStorageClient:
    def __init__(self, *, project: str | None) -> None:
        assert project == "stratus-test"
        self.bucket_instance = FakeBucket()

    def bucket(self, name: str) -> FakeBucket:
        assert name == "inspection-photos"
        return self.bucket_instance


@pytest.mark.asyncio
async def test_gcs_inspection_photo_upload_returns_bucket_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeStorageClient(project="stratus-test")
    monkeypatch.setattr(storage_module.storage, "Client", lambda *, project: client)
    gateway = GCSStorageGateway("inspection-photos", "stratus-test")

    result = await gateway.upload(
        "inspector/report/photo.jpg",
        b"image-bytes",
        "image/jpeg",
        "unused-user-token",
    )

    assert result == "gs://inspection-photos/inspector/report/photo.jpg"
    assert client.bucket_instance.blob_instance.upload == (b"image-bytes", "image/jpeg")
