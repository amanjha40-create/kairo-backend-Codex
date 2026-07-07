"""Notification center enums."""

from __future__ import annotations

from enum import StrEnum


class NotificationChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    WEBHOOK = "webhook"
    SLACK = "slack"
    TEAMS = "teams"
    CUSTOM = "custom"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
