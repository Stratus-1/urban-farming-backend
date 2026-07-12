from typing import Literal

from pydantic import AnyHttpUrl, EmailStr, Field

from app.schemas.common import APIModel

# "admin" is deliberately absent: it is granted by the handle_new_user() trigger
# allowlist, never self-assigned at signup.
SignupRole = Literal["grower", "buyer", "operator", "inspector"]


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
    id_token: str = Field(min_length=1, max_length=4096)
    role: SignupRole = "grower"
