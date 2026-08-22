from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class BillingPlan(APIModel):
    code: str
    name: str
    interval: str
    amount: int = Field(ge=0)
    currency: str
    description: str
    stripe_price_id: str | None = None
    featured: bool = False


class BillingSubscription(APIModel):
    plan_code: str | None = None
    status: str = "inactive"
    active: bool = False
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    customer_id: str | None = None
    subscription_id: str | None = None


class BillingOverview(APIModel):
    plans: list[BillingPlan]
    subscription: BillingSubscription
    publishable_key: str | None = None


class CheckoutSessionResponse(APIModel):
    checkout_url: str


class PortalSessionResponse(APIModel):
    portal_url: str
