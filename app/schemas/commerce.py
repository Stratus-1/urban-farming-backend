from datetime import date
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class OrderItemCreate(APIModel):
    crop_id: UUID
    quantity_kg: float = Field(gt=0, le=100_000)
    unit_price: float = Field(ge=0, le=1_000_000)


class OrderCreate(APIModel):
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)
    delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
