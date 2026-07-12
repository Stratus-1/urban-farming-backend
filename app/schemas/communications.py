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


class CalculatorPlanUpsert(APIModel):
    calculator_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
