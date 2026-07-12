from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class InspectionStart(APIModel):
    assignment_id: UUID
    gps_lat: float | None = Field(default=None, ge=-90, le=90)
    gps_lng: float | None = Field(default=None, ge=-180, le=180)


class ChecklistItemUpsert(APIModel):
    category: str = Field(min_length=1, max_length=120)
    item_name: str = Field(min_length=1, max_length=200)
    result: Literal["pass", "warning", "fail", "na"] = "na"
    comment: str | None = Field(default=None, max_length=2000)
    requires_photo: bool = False
    sort_order: int = Field(default=0, ge=0, le=1000)


class InspectionSubmit(APIModel):
    report_id: UUID
    overall_status: Literal["pass", "warning", "fail"]
    notes: str | None = Field(default=None, max_length=4000)
    follow_up_required: bool = False
    gps_lat: float | None = Field(default=None, ge=-90, le=90)
    gps_lng: float | None = Field(default=None, ge=-180, le=180)
