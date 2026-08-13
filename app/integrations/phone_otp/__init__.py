"""Phone OTP delivery adapters."""

from app.integrations.phone_otp.sender import (
    ConsolePhoneOtpSender,
    Msg91ClientManagedPhoneOtpSender,
    PhoneOtpSender,
    SnsPhoneOtpSender,
    StagingFixedPhoneOtpSender,
    get_phone_otp_sender,
)
from app.integrations.phone_otp.verifier import (
    Msg91PhoneOtpVerifier,
    PhoneOtpVerifier,
    PhoneVerificationResult,
    get_phone_otp_verifier,
)

__all__ = [
    "ConsolePhoneOtpSender",
    "Msg91ClientManagedPhoneOtpSender",
    "Msg91PhoneOtpVerifier",
    "PhoneOtpSender",
    "PhoneOtpVerifier",
    "PhoneVerificationResult",
    "SnsPhoneOtpSender",
    "StagingFixedPhoneOtpSender",
    "get_phone_otp_sender",
    "get_phone_otp_verifier",
]
