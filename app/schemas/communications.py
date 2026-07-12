from typing import Any

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
