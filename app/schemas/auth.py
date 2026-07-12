"""Authentication request/response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    phone: str = Field(..., min_length=8, max_length=32)
    password: str = Field(..., min_length=12, max_length=128, description="Minimum length enforced server-side")
    full_name: str | None = Field(None, max_length=255)


class SignupStartResponse(BaseModel):
    """Staged signup created — verify both channels before tokens are issued."""

    signup_session_id: UUID
    email_masked: str
    phone_masked: str
    email_verified: bool = False
    phone_verified: bool = False
    email_resend_after_seconds: int
    phone_resend_after_seconds: int
    expires_in_seconds: int
    message: str = "Signup session created"


class SignupChannelRequest(BaseModel):
    signup_session_id: UUID


class SignupChannelSendResponse(BaseModel):
    signup_session_id: UUID
    channel: str
    verified: bool
    email_verified: bool
    phone_verified: bool
    resend_after_seconds: int
    expires_in_seconds: int
    email_masked: str | None = None
    phone_masked: str | None = None
    message: str = "Verification code sent"


class SignupVerifyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    signup_session_id: UUID
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def digits_only(cls, v: str) -> str:
        if not v.isdigit():
            msg = "code must be a 6-digit number"
            raise ValueError(msg)
        return v


class SignupChannelVerifyResponse(BaseModel):
    signup_session_id: UUID
    channel: str
    verified: bool = True
    email_verified: bool
    phone_verified: bool
    message: str


class SignupCompleteRequest(BaseModel):
    signup_session_id: UUID


class SignupResendRequest(BaseModel):
    signup_session_id: UUID


class SignupResendResponse(BaseModel):
    signup_session_id: UUID
    email_masked: str
    resend_after_seconds: int
    message: str = "Verification code sent"


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str = "If an account exists for that email, a password reset email has been sent."


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(..., min_length=20, max_length=512)
    new_password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class ResetPasswordResponse(BaseModel):
    message: str = "Password reset successful."


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class TokenResponse(BaseModel):
    """OAuth2-ish token bundle — refresh token returned at issuance and each rotation."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token TTL in seconds")


class OAuthAuthUrlResponse(BaseModel):
    provider: str
    auth_url: str


class OAuthCallbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, description="Authorization code returned by the provider redirect")


class SetPasswordRequest(BaseModel):
    """Allow a social-only user to add email/password login to their account."""

    model_config = ConfigDict(str_strip_whitespace=True)

    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class SetPasswordResponse(BaseModel):
    message: str = "Password set successfully. You can now also log in with email and password."


class ChangePasswordRequest(BaseModel):
    """Change an existing password — requires the current password for verification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class ChangePasswordResponse(BaseModel):
    message: str = "Password changed successfully."


class LinkProviderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, description="Authorization code from provider redirect")


class LinkProviderResponse(BaseModel):
    message: str = "Account linked successfully."
    provider: str
    provider_email: str


class UnlinkProviderResponse(BaseModel):
    message: str = "Account unlinked successfully."
    provider: str
