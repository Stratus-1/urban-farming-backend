from typing import Literal

from pydantic import AnyHttpUrl, EmailStr, Field, model_validator

from app.schemas.common import APIModel

# "admin" is deliberately absent: it is granted by the handle_new_user() trigger
# allowlist, never self-assigned at signup.
SignupRole = Literal["grower", "buyer"]


class SignupRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    full_name: str = Field(min_length=1, max_length=120)
    role: SignupRole = "grower"
    redirect_to: AnyHttpUrl | None = None


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(APIModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(APIModel):
    scope: Literal["global", "local", "others"] = "global"


class PasswordResetRequest(APIModel):
    email: EmailStr
    redirect_to: AnyHttpUrl | None = None


class PasswordUpdateRequest(APIModel):
    password: str = Field(min_length=6, max_length=72)


class GoogleSignInRequest(APIModel):
    id_token: str | None = Field(default=None, min_length=1, max_length=4096)
    code: str | None = Field(default=None, min_length=1, max_length=4096)
    redirect_uri: AnyHttpUrl | None = None
    role: SignupRole = "grower"

    @property
    def is_code_flow(self) -> bool:
        return bool(self.code)

    @property
    def is_id_token_flow(self) -> bool:
        return bool(self.id_token)

    @model_validator(mode="after")
    def validate_flow(self):
        if self.is_code_flow == self.is_id_token_flow:
            raise ValueError("Provide exactly one of code or id_token")
        if self.is_code_flow and self.redirect_uri is None:
            raise ValueError("redirect_uri is required when exchanging an authorization code")
        return self
