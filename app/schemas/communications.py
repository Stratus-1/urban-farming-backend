from datetime import datetime
from typing import Any, Literal

from pydantic import EmailStr, Field

from app.schemas.common import APIModel


class ContactMessageCreate(APIModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=10_000)


class NewsletterSignup(APIModel):
    email: EmailStr
    source: str = Field(default="landing", max_length=80)


class AssessmentLeadCreate(APIModel):
    full_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    suburb: str = Field(min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    space_type: Literal[
        "backyard",
        "front_yard",
        "balcony",
        "patio",
        "courtyard",
        "rooftop",
        "windowsill",
        "indoor",
        "vertical_wall",
        "community_plot",
        "other",
    ]
    available_space_m2: float = Field(gt=0, le=100_000)
    sunlight_hours: float = Field(ge=0, le=24)
    water_access: Literal["none", "limited", "reliable", "unknown"] = "unknown"
    interest_type: Literal[
        "personal_harvest",
        "learn_to_grow",
        "community_contribution",
        "payout",
        "buyer_supply",
        "not_sure",
    ] = "not_sure"
    message: str | None = Field(default=None, max_length=4000)
    source: str = Field(default="assessment_page", max_length=80)


class AssessmentLeadStatusUpdate(APIModel):
    status: Literal[
        "new", "contacted", "scheduled", "assessed", "converted", "not_viable", "closed"
    ]
    admin_notes: str | None = Field(default=None, max_length=4000)


class AssessmentLeadConvert(APIModel):
    label: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=240)
    city: str | None = Field(default=None, max_length=120)
    admin_notes: str | None = Field(default=None, max_length=4000)


class HelpCenterGardenRequestCase(APIModel):
    """Minimized, product-owned lifecycle projection; deliberately excludes contact content."""

    case_ref: str = Field(pattern=r"^ufc-[a-f0-9]{28}$")
    tenant_scope_ref: str = Field(pattern=r"^uf-tenant-[a-f0-9]{64}$")
    requester_ref: str = Field(pattern=r"^uf-user-[a-f0-9]{64}$")
    category: Literal["garden_request"] = "garden_request"
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
    created_at: datetime
    updated_at: datetime


class HelpCenterGardenRequestSnapshot(APIModel):
    contract_version: Literal["1.0"] = "1.0"
    product_id: Literal["urban_farming"] = "urban_farming"
    items: list[HelpCenterGardenRequestCase]
    snapshot_at: datetime


class GardenRequestNotification(APIModel):
    request_id: str = Field(min_length=1, max_length=120)
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=160)
    garden_name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=240)
    city: str | None = Field(default=None, max_length=120)
    lat: float | None = None
    lng: float | None = None
    garden_type: str | None = Field(default=None, max_length=80)
    plants: list[str] = Field(default_factory=list, max_length=50)


class SignupNotification(APIModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=40)


class CalculatorPlanUpsert(APIModel):
    calculator_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)


class MobilePushNotificationCreate(APIModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=240)
    user_ids: list[str] = Field(default_factory=list, max_length=200)
    roles: list[str] = Field(default_factory=list, max_length=20)
    data: dict[str, str] = Field(default_factory=dict)
    image_url: str | None = Field(default=None, max_length=2048)
    deep_link: str | None = Field(default=None, max_length=2048)
