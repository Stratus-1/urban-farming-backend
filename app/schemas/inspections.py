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


class InspectionRisk(APIModel):
    category: Literal[
        "access",
        "security",
        "flooding",
        "drainage",
        "contamination",
        "pests",
        "animals",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    notes: str = Field(min_length=1, max_length=500)


class InspectionAssessment(APIModel):
    sunlight_hours: float = Field(ge=0, le=24)
    water_access: Literal["none", "limited", "reliable"]
    usable_space_m2: float = Field(gt=0, le=100000)
    installation_types: list[
        Literal[
            "raised_bed",
            "in_ground",
            "container",
            "vertical",
            "greenhouse",
            "hydroponic",
            "wicking_bed",
        ]
    ] = Field(min_length=1)
    measurements: dict[str, float] = Field(default_factory=dict)
    risks: list[InspectionRisk] = Field(default_factory=list)
    recommended_crops: list[str] = Field(default_factory=list, max_length=30)
    recommended_infrastructure: list[str] = Field(default_factory=list, max_length=30)


class InspectionAssessmentResult(InspectionAssessment):
    suitability_score: int = Field(ge=0, le=100)
    score_breakdown: dict[str, int]
    suitability_band: Literal["suitable", "conditional", "not_suitable"]
