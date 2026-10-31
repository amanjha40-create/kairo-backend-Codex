"""Stable client errors for password capability transitions."""

from app.exceptions import ConflictError, ForbiddenError, UnauthorizedError


class PasswordAlreadySetError(ConflictError):
    def __init__(self) -> None:
        super().__init__("A password is already set. Use change-password instead.")
        self.code = "password_already_set"


class PasswordNotSetError(ConflictError):
    def __init__(self) -> None:
        super().__init__("No password is set. Use set-password instead.")
        self.code = "password_not_set"


class SetPasswordNotEligibleError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("This account cannot use the first-password flow.")
        self.code = "set_password_not_eligible"


class InvalidCurrentPasswordError(UnauthorizedError):
    def __init__(self) -> None:
        super().__init__("Current password is incorrect")
        self.code = "invalid_current_password"


class InvalidSetPasswordChallengeError(UnauthorizedError):
    def __init__(self) -> None:
        super().__init__("Invalid or expired verification code")
        self.code = "invalid_or_expired_challenge"
