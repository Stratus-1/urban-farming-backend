from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CurrentUser(BaseModel):
    id: UUID
    email: EmailStr | None = None
    roles: set[str] = Field(default_factory=set)
    access_token: str

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


class HealthResponse(BaseModel):
    status: str
    service: str = "urban-farming-backend"
    environment: str
    data_backend: str
    timestamp: datetime


class ListResponse(BaseModel):
    items: list[dict[str, Any]]
    count: int


class MessageResponse(BaseModel):
    ok: bool = True
    message: str


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
