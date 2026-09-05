"""Authentication HTTP surface — OTP signup, email/password login, OAuth providers, token lifecycle."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.rate_limit import (
    auth_rate_limit,
    otp_verify_rate_limit,
    signup_recovery_rate_limit,
)
from app.api.dependencies.services import get_auth_service
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LinkProviderRequest,
    LinkProviderResponse,
    LoginRequest,
    OAuthAuthUrlResponse,
    OAuthCallbackRequest,
    GoogleHandoffExchangeRequest,
    GoogleHandoffExchangeResponse,
    GooglePhoneStartRequest,
    OrganizationSignupEmailSendResponse,
    OrganizationSignupEmailVerifyResponse,
    OrganizationSignupStartRequest,
    OrganizationSignupStartResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SetPasswordRequest,
    SetPasswordResponse,
    SignupChannelRequest,
    SignupChannelSendResponse,
    SignupChannelVerifyResponse,
    SignupCompleteRequest,
    SignupResendRequest,
    SignupResendResponse,
    SignupSessionRecoveryResponse,
    SignupStartResponse,
    SignupVerifyRequest,
    TokenResponse,
    UnlinkProviderResponse,
)
from app.services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

organization_signup_router = APIRouter(prefix="/auth/organization/signup", tags=["organization-auth"])


@organization_signup_router.post(
    "/start",
    response_model=OrganizationSignupStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start email-only organization staff signup",
    dependencies=[Depends(auth_rate_limit)],
)
async def organization_signup_start(
    payload: OrganizationSignupStartRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> OrganizationSignupStartResponse:
    return await auth.start_organization_signup(payload)


@organization_signup_router.post(
    "/email/send",
    response_model=OrganizationSignupEmailSendResponse,
    summary="Send organization staff signup email OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def organization_signup_email_send(
    payload: SignupChannelRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> OrganizationSignupEmailSendResponse:
    return await auth.send_organization_signup_email_otp(payload)


@organization_signup_router.post(
    "/email/verify",
    response_model=OrganizationSignupEmailVerifyResponse,
    summary="Verify organization staff signup email OTP",
    dependencies=[Depends(otp_verify_rate_limit)],
)
async def organization_signup_email_verify(
    payload: SignupVerifyRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> OrganizationSignupEmailVerifyResponse:
    return await auth.verify_organization_signup_email(payload)


@organization_signup_router.post(
    "/complete",
    response_model=TokenResponse,
    summary="Complete organization staff signup and create a session",
    dependencies=[Depends(auth_rate_limit)],
)
async def organization_signup_complete(
    payload: SignupCompleteRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await auth.complete_organization_signup(payload)


# ---------------------------------------------------------------------------
# Email / password signup + login
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=SignupStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start staged signup — creates signup session",
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
    summary="Start staged signup — creates signup session",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_start(
    payload: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupStartResponse:
    return await auth.start_signup(payload)


@router.get(
    "/signup/session",
    response_model=SignupSessionRecoveryResponse,
    summary="Recover Candidate signup session state without side effects",
    description=(
        "Read-only pre-account recovery lookup. The required X-Signup-Session-ID header "
        "is the opaque UUIDv4 credential issued by signup/start. It is carried in a header "
        "instead of the URL so structured access logs do not capture the credential. The "
        "response contains masked contacts only, does not require a Candidate bearer JWT, "
        "and never sends or verifies an OTP, completes signup, or mutates session state."
    ),
    responses={
        404: {"description": "Signup session is unknown or not a Candidate signup session"},
        422: {"description": "The recovery credential is missing or malformed"},
        429: {"description": "Too many recovery lookups from this client"},
    },
    dependencies=[Depends(signup_recovery_rate_limit)],
)
async def recover_signup_session(
    signup_session_id: Annotated[
        UUID,
        Header(
            alias="X-Signup-Session-ID",
            description=(
                "Opaque pre-account signup recovery credential returned by signup/start. "
                "Store and transmit it as a secret over HTTPS."
            ),
        ),
    ],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> SignupSessionRecoveryResponse:
    return await auth.recover_signup_session(signup_session_id)


@router.post(
    "/signup/email/send",
    response_model=SignupChannelSendResponse,
    summary="Send signup email OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_email_send(
    payload: SignupChannelRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelSendResponse:
    return await auth.send_signup_email_otp(payload)


@router.post(
    "/signup/email/resend",
    response_model=SignupChannelSendResponse,
    summary="Resend signup email OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_email_resend(
    payload: SignupChannelRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelSendResponse:
    return await auth.resend_signup_email_otp(payload)


@router.post(
    "/signup/email/verify",
    response_model=SignupChannelVerifyResponse,
    summary="Verify signup email OTP",
    dependencies=[Depends(otp_verify_rate_limit)],
)
async def signup_email_verify(
    payload: SignupVerifyRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelVerifyResponse:
    return await auth.verify_signup_email(payload)


@router.post(
    "/signup/phone/send",
    response_model=SignupChannelSendResponse,
    summary="Send signup phone OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_phone_send(
    payload: SignupChannelRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelSendResponse:
    return await auth.send_signup_phone_otp(payload)


@router.post(
    "/signup/google/phone",
    response_model=SignupStartResponse,
    summary="Add phone number after verified Google signup",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_google_phone_start(
    payload: GooglePhoneStartRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupStartResponse:
    return await auth.start_google_phone_verification(payload)


@router.post(
    "/signup/phone/resend",
    response_model=SignupChannelSendResponse,
    summary="Resend signup phone OTP",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_phone_resend(
    payload: SignupChannelRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelSendResponse:
    return await auth.resend_signup_phone_otp(payload)


@router.post(
    "/signup/phone/verify",
    response_model=SignupChannelVerifyResponse,
    summary="Verify signup phone OTP",
    dependencies=[Depends(otp_verify_rate_limit)],
)
async def signup_phone_verify(
    payload: SignupVerifyRequest,
    auth: AuthService = Depends(get_auth_service),
) -> SignupChannelVerifyResponse:
    return await auth.verify_signup_phone(payload)


@router.post(
    "/signup/complete",
    response_model=TokenResponse,
    summary="Complete staged signup after both channels are verified",
    dependencies=[Depends(auth_rate_limit)],
)
async def signup_complete(
    payload: SignupCompleteRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth.complete_signup(payload)


@router.post(
    "/signup/verify",
    response_model=TokenResponse,
    summary="Legacy signup verify alias — verifies email and completes if phone already verified",
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
    summary="Legacy signup resend alias — resends email OTP",
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


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset token",
    dependencies=[Depends(auth_rate_limit)],
)
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    auth: AuthService = Depends(get_auth_service),
) -> ForgotPasswordResponse:
    requested_base_url = request.headers.get("origin") or request.headers.get("referer")
    return await auth.forgot_password(payload, requested_base_url=requested_base_url)


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    summary="Reset password using a one-time token",
    dependencies=[Depends(auth_rate_limit)],
)
async def reset_password(
    payload: ResetPasswordRequest,
    auth: AuthService = Depends(get_auth_service),
) -> ResetPasswordResponse:
    return await auth.reset_password(payload)


# ---------------------------------------------------------------------------
# Google OAuth — state/PKCE is mandatory and its callback is browser-only.
# ---------------------------------------------------------------------------

@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    auth: AuthService = Depends(get_auth_service),
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    handoff_code = await auth.complete_google_callback(code=code, state=state_value, error=error)
    handoff_uri = auth.google_app_handoff_uri
    if not handoff_uri:
        # A generic failure avoids revealing deployment configuration to the browser.
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        f"{handoff_uri}?{urlencode({'code': handoff_code})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/google/handoff/exchange",
    response_model=GoogleHandoffExchangeResponse,
    summary="Consume one-time Google Android App Link handoff",
    dependencies=[Depends(auth_rate_limit)],
)
async def google_handoff_exchange(
    payload: GoogleHandoffExchangeRequest,
    auth: AuthService = Depends(get_auth_service),
) -> GoogleHandoffExchangeResponse:
    return await auth.exchange_google_handoff(payload.code)


# OAuth providers — generic /{provider}/ routes (linkedin, github, ...).
# Google is deliberately intercepted above so it cannot use the legacy exchange.
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

    if provider == "google":
        return await auth.start_google_oauth()
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

    if provider == "google":
        # Google only accepts the state-bound browser callback above.
        return Response(status_code=status.HTTP_404_NOT_FOUND)
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
