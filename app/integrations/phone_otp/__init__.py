"""Phone OTP delivery adapters."""

from app.integrations.phone_otp.msg91 import Msg91DispatchResult, Msg91PhoneOtpProvider
from app.integrations.phone_otp.sender import (
    ConsolePhoneOtpSender,
    PhoneOtpSender,
    SnsPhoneOtpSender,
    get_phone_otp_sender,
)

__all__ = [
    "ConsolePhoneOtpSender",
    "Msg91DispatchResult",
    "Msg91PhoneOtpProvider",
    "PhoneOtpSender",
    "SnsPhoneOtpSender",
    "get_phone_otp_sender",
]
