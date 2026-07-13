"""User account — credentials, profile, and RBAC role."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Role
from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken
    from app.models.user_social_account import UserSocialAccount


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Application user — email login, password hash, and single role string."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_slug: Mapped[str | None] = mapped_column(String(100), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    current_role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_of_experience: Mapped[int | None] = mapped_column(nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=Role.USER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    employment_onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    social_accounts: Mapped[list["UserSocialAccount"]] = relationship(
        "UserSocialAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"User(id={self.id}, email={self.email!r})"
