"""Authentication HTTP surface — OTP signup, email/password login, OAuth providers, token lifecycle."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.rate_limit import auth_rate_limit, otp_verify_rate_limit
from app.api.dependencies.services import get_auth_service
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LinkProviderRequest,
    LinkProviderResponse,
    LoginRequest,
    OAuthAuthUrlResponse,
    OAuthCallbackRequest,
    RefreshRequest,
    RegisterRequest,
    SetPasswordRequest,
    SetPasswordResponse,
    SignupResendRequest,
    SignupResendResponse,
    SignupStartResponse,
    SignupVerifyRequest,
    TokenResponse,
    UnlinkProviderResponse,
)
from app.services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Email / password signup + login
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=SignupStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start signup — sends email OTP (no tokens until verify)",
    dependencies=[Depends(auth_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupStartResponse:
    return await auth.start_signup(payload)


@router.post(
    "/signup/start",
    response_model=SignupStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start signup — sends email OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_start(
    payload: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupStartResponse:
    return await auth.start_signup(payload)


@router.post(
    "/signup/verify",
    response_model=TokenResponse,
    summary="Verify email OTP and complete signup",
    dependencies=[Depends(otp_verify_rate_limit)],
)
async def signup_verify(
    payload: SignupVerifyRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth.verify_signup(payload)


@router.post(
    "/signup/resend",
    response_model=SignupResendResponse,
    summary="Resend signup OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_resend(
    payload: SignupResendRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupResendResponse:
    return await auth.resend_signup_otp(payload)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    dependencies=[Depends(auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth.login(payload)


# ---------------------------------------------------------------------------
# OAuth providers — generic /{provider}/ routes (google, linkedin, github, ...)
# ---------------------------------------------------------------------------

@router.get(
    "/{provider}/url",
    response_model=OAuthAuthUrlResponse,
    summary="Get OAuth2 authorization URL for a provider",
)
async def oauth_url(
    provider: str,
    auth: AuthService = Depends(get_auth_service),
) -> OAuthAuthUrlResponse:
    """Returns the provider's login URL. Supported: google, linkedin, github."""

    return auth.get_oauth_url(provider)


@router.post(
    "/{provider}/callback",
    response_model=TokenResponse,
    summary="Exchange OAuth2 auth code for app tokens",
)
async def oauth_callback(
    provider: str,
    payload: OAuthCallbackRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Exchange the authorization code returned by the provider for app JWT tokens."""

    return await auth.oauth_callback(provider, payload)


@router.post(
    "/{provider}/link",
    response_model=LinkProviderResponse,
    summary="Link an OAuth provider to the current account",
)
async def link_provider(
    provider: str,
    payload: LinkProviderRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: AuthService = Depends(get_auth_service),
) -> LinkProviderResponse:
    """Authenticated users can link any OAuth provider to enable multiple login methods."""

    return await auth.link_provider(current.id, provider, payload)


@router.delete(
    "/{provider}/unlink",
    response_model=UnlinkProviderResponse,
    summary="Unlink an OAuth provider from the current account",
)
async def unlink_provider(
    provider: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: AuthService = Depends(get_auth_service),
) -> UnlinkProviderResponse:
    """Remove a linked OAuth provider. Blocked if it is the only login method."""

    return await auth.unlink_provider(current.id, provider)


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

@router.post(
    "/set-password",
    response_model=SetPasswordResponse,
    summary="Set password — enables email/password login for social-only accounts",
)
async def set_password(
    payload: SetPasswordRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: AuthService = Depends(get_auth_service),
) -> SetPasswordResponse:
    return await auth.set_password(current.id, payload)


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Change password — verifies the current password before updating",
)
async def change_password(
    payload: ChangePasswordRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: AuthService = Depends(get_auth_service),
) -> ChangePasswordResponse:
    return await auth.change_password(current.id, payload)


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenResponse, summary="Rotate refresh token")
async def refresh(
    payload: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth.refresh(payload)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke refresh token")
async def logout(
    payload: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> Response:
    await auth.logout(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
