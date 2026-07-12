from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class GardenRequestCreate(APIModel):
    label: str = Field(min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=240)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    available_space_m2: float | None = Field(default=None, ge=0, le=100_000)
    sunlight_hours: float | None = Field(default=None, ge=0, le=24)
    details: dict[str, Any] = Field(default_factory=dict)


class GardenRequestStatusUpdate(APIModel):
    status: Literal[
        "submitted",
        "inspection_scheduled",
        "accepted",
        "needing_implements",
        "implements_installed",
        "seeds",
        "final_install",
        "live",
        "rejected",
        "cancelled",
    ]
    admin_notes: str | None = Field(default=None, max_length=4000)


class GardenAllocationCreate(APIModel):
    allocated_plants: list[str] = Field(min_length=1, max_length=50)
    inspection_notes: str | None = Field(default=None, max_length=4000)
    allocation_notes: str | None = Field(default=None, max_length=4000)


class CareActionCreate(APIModel):
    installation_id: UUID | None = None
    action_type: Literal["watering", "feeding", "pruning", "inspection", "pest_check"]
    occurred_at: datetime
    amount: float | None = Field(default=None, ge=0, le=10_000)
    unit: str | None = Field(default=None, max_length=24)
    method: str | None = Field(default=None, max_length=80)
    crop_focus: str | None = Field(default=None, max_length=120)
    condition: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class GardenTaskCreate(APIModel):
    property_id: UUID
    installation_id: UUID | None = None
    task_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    due_at: date | None = None
