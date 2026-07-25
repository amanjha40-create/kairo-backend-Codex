"""Central application configuration — twelve-factor, typed, validated.

Environment variables use SCREAMING_SNAKE_CASE. Values are documented in `.env.example`.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
import re
from math import isclose
from typing import Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Deployment slice — drives stricter validation in production."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """Load-time validated settings — immutable after first access via `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Application ---
    app_name: str = Field(default="kairo-backend", validation_alias=AliasChoices("APP_NAME"))
    app_env: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT, validation_alias=AliasChoices("APP_ENV"))
    app_version: str = Field(default="0.1.0", validation_alias=AliasChoices("APP_VERSION"))
    api_v1_prefix: str = Field(default="/api/v1", validation_alias=AliasChoices("API_V1_PREFIX"))

    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("HOST"))
    port: int = Field(default=8000, ge=1, le=65535, validation_alias=AliasChoices("PORT"))

    # --- Observability ---
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))
    log_json: bool = Field(default=True, validation_alias=AliasChoices("LOG_JSON"))
    log_access_enabled: bool = Field(
        default=True,
        description="Structured HTTP access logs via middleware; dims duplicate uvicorn.access",
        validation_alias=AliasChoices("LOG_ACCESS_ENABLED"),
    )

    # --- Database (async SQLAlchemy runtime) ---
    database_url: str = Field(
        ...,
        description="postgresql+asyncpg://user:pass@host:5432/dbname",
        validation_alias=AliasChoices("DATABASE_URL"),
    )
    database_pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias=AliasChoices("DATABASE_POOL_SIZE"),
    )
    database_max_overflow: int = Field(
        default=20,
        ge=0,
        le=100,
        validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW"),
    )
    database_pool_timeout: float = Field(
        default=30.0,
        ge=1,
        validation_alias=AliasChoices("DATABASE_POOL_TIMEOUT"),
    )
    database_echo_sql: bool | None = Field(
        default=None,
        description="Log SQL statements; when unset, echoes only in development",
        validation_alias=AliasChoices("DATABASE_ECHO_SQL"),
    )

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL"),
    )
    redis_max_connections: int = Field(
        default=50,
        ge=1,
        le=500,
        validation_alias=AliasChoices("REDIS_MAX_CONNECTIONS"),
    )
    redis_socket_connect_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=120.0,
        validation_alias=AliasChoices("REDIS_SOCKET_CONNECT_TIMEOUT"),
    )
    redis_socket_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=120.0,
        validation_alias=AliasChoices("REDIS_SOCKET_TIMEOUT"),
    )
    redis_health_check_interval: int = Field(
        default=30,
        ge=0,
        description="Seconds between connection health checks in the pool; 0 may disable depending on client",
        validation_alias=AliasChoices("REDIS_HEALTH_CHECK_INTERVAL"),
    )
    redis_key_prefix: str = Field(
        default="",
        description="Override key namespace; empty uses APP_NAME:APP_ENV",
        validation_alias=AliasChoices("REDIS_KEY_PREFIX"),
    )
    redis_required_for_ready: bool = Field(
        default=False,
        description="If true, /health/ready returns 503 when Redis is unreachable",
        validation_alias=AliasChoices("REDIS_REQUIRED_FOR_READY"),
    )

    # --- JWT ---
    jwt_secret_key: str = Field(
        ...,
        min_length=32,
        description="HS256 signing secret — rotate via deployment",
        validation_alias=AliasChoices("JWT_SECRET_KEY"),
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias=AliasChoices("JWT_ALGORITHM"))
    jwt_access_ttl_minutes: int = Field(
        default=15,
        ge=1,
        le=24 * 60,
        validation_alias=AliasChoices("JWT_ACCESS_TTL_MINUTES"),
    )
    jwt_refresh_ttl_days: int = Field(default=7, ge=1, le=365, validation_alias=AliasChoices("JWT_REFRESH_TTL_DAYS"))

    # --- Signup email OTP ---
    signup_otp_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        validation_alias=AliasChoices("SIGNUP_OTP_TTL_SECONDS"),
    )
    signup_otp_resend_cooldown_seconds: int = Field(
        default=30,
        ge=10,
        le=300,
        validation_alias=AliasChoices("SIGNUP_OTP_RESEND_COOLDOWN_SECONDS"),
    )
    signup_otp_max_verify_attempts: int = Field(
        default=5,
        ge=3,
        le=20,
        validation_alias=AliasChoices("SIGNUP_OTP_MAX_VERIFY_ATTEMPTS"),
    )
    signup_otp_max_sends_per_hour: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias=AliasChoices("SIGNUP_OTP_MAX_SENDS_PER_HOUR"),
    )
    signup_pending_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        validation_alias=AliasChoices("SIGNUP_PENDING_TTL_HOURS"),
    )
    phone_default_country_code: str = Field(
        default="+91",
        description="Used only when a signup phone number omits the leading +country code.",
        validation_alias=AliasChoices("PHONE_DEFAULT_COUNTRY_CODE"),
    )
    phone_otp_backend: str = Field(
        default="console",
        description="console | staging_fixed | real_provider_placeholder",
        validation_alias=AliasChoices("PHONE_OTP_BACKEND"),
    )
    phone_otp_enabled: bool = Field(
        default=True,
        description="Enables staged phone OTP verification during signup.",
        validation_alias=AliasChoices("PHONE_OTP_ENABLED"),
    )
    staging_phone_otp_code: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("STAGING_PHONE_OTP_CODE"),
    )
    auth_rate_limit_max_requests: int = Field(
        default=10, ge=1, le=1000, validation_alias=AliasChoices("AUTH_RATE_LIMIT_MAX_REQUESTS")
    )
    auth_rate_limit_window_seconds: int = Field(
        default=60, ge=1, le=3600, validation_alias=AliasChoices("AUTH_RATE_LIMIT_WINDOW_SECONDS")
    )
    # --- Versioned Trust Score configuration ---
    trust_score_version: str = Field(default="v1", validation_alias=AliasChoices("TRUST_SCORE_VERSION"))
    trust_score_identity_weight: float = Field(default=0.25, ge=0, le=1, validation_alias=AliasChoices("TRUST_SCORE_IDENTITY_WEIGHT"))
    trust_score_employment_weight: float = Field(default=0.45, ge=0, le=1, validation_alias=AliasChoices("TRUST_SCORE_EMPLOYMENT_WEIGHT"))
    trust_score_education_weight: float = Field(default=0.30, ge=0, le=1, validation_alias=AliasChoices("TRUST_SCORE_EDUCATION_WEIGHT"))
    trust_score_require_consent: bool = Field(default=True, validation_alias=AliasChoices("TRUST_SCORE_REQUIRE_CONSENT"))
    otp_verify_rate_limit_max_requests: int = Field(
        default=5, ge=1, le=100, validation_alias=AliasChoices("OTP_VERIFY_RATE_LIMIT_MAX_REQUESTS")
    )
    otp_verify_rate_limit_window_seconds: int = Field(
        default=60, ge=1, le=3600, validation_alias=AliasChoices("OTP_VERIFY_RATE_LIMIT_WINDOW_SECONDS")
    )
    password_reset_token_ttl_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        validation_alias=AliasChoices("PASSWORD_RESET_TOKEN_TTL_MINUTES"),
    )
    email_from: str = Field(
        default="noreply@kairo.app",
        validation_alias=AliasChoices("EMAIL_FROM"),
    )
    email_reply_to: str = Field(
        default="support@kairoid.com",
        validation_alias=AliasChoices("EMAIL_REPLY_TO"),
    )
    email_backend: str = Field(
        default="console",
        description="console | smtp | ses — external delivery requires EMAIL_SEND_ENABLED=true",
        validation_alias=AliasChoices("EMAIL_BACKEND"),
    )
    email_send_enabled: bool = Field(
        default=False,
        description="If false, providers must not attempt real external email delivery.",
        validation_alias=AliasChoices("EMAIL_SEND_ENABLED"),
    )
    email_dev_log_secrets: bool = Field(
        default=False,
        description="Local debugging only — allows console provider to include secrets in logs outside production.",
        validation_alias=AliasChoices("EMAIL_DEV_LOG_SECRETS"),
    )
    smtp_host: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_HOST"))
    smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias=AliasChoices("SMTP_PORT"))
    smtp_user: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_USER"))
    smtp_password: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_PASSWORD"))
    smtp_use_tls: bool = Field(
        default=True,
        description="STARTTLS on port 587 (Gmail, Brevo, Mailgun SMTP)",
        validation_alias=AliasChoices("SMTP_USE_TLS"),
    )
    smtp_use_ssl: bool = Field(
        default=False,
        description="Implicit SSL on port 465 — do not combine with SMTP_USE_TLS",
        validation_alias=AliasChoices("SMTP_USE_SSL"),
    )
    smtp_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        validation_alias=AliasChoices("SMTP_TIMEOUT_SECONDS"),
    )
    ses_from_email: str | None = Field(
        default=None, validation_alias=AliasChoices("SES_FROM_EMAIL")
    )

    # --- Employer verification magic links ---
    app_public_base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL embedded in employer verification emails (API or web app)",
        validation_alias=AliasChoices("APP_PUBLIC_BASE_URL"),
    )
    employer_portal_base_url: str | None = Field(
        default=None,
        description="Frontend origin used for employer verification magic links",
        validation_alias=AliasChoices("EMPLOYER_PORTAL_BASE_URL"),
    )
    employer_verification_token_ttl_hours: int = Field(
        default=168,
        ge=24,
        le=720,
        description="Hours before employer confirm/decline links expire",
        validation_alias=AliasChoices("EMPLOYER_VERIFICATION_TOKEN_TTL_HOURS"),
    )

    # --- AWS / messaging (optional) ---
    aws_region: str | None = Field(default=None, validation_alias=AliasChoices("AWS_REGION"))
    aws_endpoint_url: str | None = Field(
        default=None,
        description="LocalStack / custom endpoint override for AWS SDK clients",
        validation_alias=AliasChoices("AWS_ENDPOINT_URL"),
    )
    sqs_main_queue_url: str | None = Field(default=None, validation_alias=AliasChoices("SQS_MAIN_QUEUE_URL"))
    sqs_dlq_url: str | None = Field(default=None, validation_alias=AliasChoices("SQS_DLQ_URL"))
    sqs_receive_wait_seconds: int = Field(
        default=20,
        ge=0,
        le=20,
        description="SQS long-poll wait time (ReceiveMessage WaitTimeSeconds)",
        validation_alias=AliasChoices("SQS_RECEIVE_WAIT_SECONDS"),
    )
    sqs_max_messages_per_poll: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias=AliasChoices("SQS_MAX_MESSAGES_PER_POLL"),
    )
    job_backend: str = Field(
        default="inline",
        description="inline | sqs — inline is the safe local-development default.",
        validation_alias=AliasChoices("JOB_BACKEND"),
    )

    # --- Object storage (employment evidence) ---
    s3_documents_bucket: str | None = Field(
        default=None,
        description="Private bucket for employment verification uploads",
        validation_alias=AliasChoices("S3_DOCUMENTS_BUCKET"),
    )
    s3_presigned_put_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="TTL for presigned PUT URLs returned to clients",
        validation_alias=AliasChoices("S3_PRESIGNED_PUT_TTL_SECONDS"),
    )
    employment_max_upload_bytes: int = Field(
        default=15_000_000,
        ge=1024,
        le=500_000_000,
        description="Maximum allowed document size for upload intents",
        validation_alias=AliasChoices("EMPLOYMENT_MAX_UPLOAD_BYTES"),
    )
    s3_document_key_prefix: str = Field(
        default="employment-verification",
        min_length=1,
        max_length=512,
        description="Leading prefix for object keys — bucket policies often scope on this path",
        validation_alias=AliasChoices("S3_DOCUMENT_KEY_PREFIX"),
    )
    s3_allowed_upload_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
        description="Allowlisted MIME primary types for client-declared uploads",
        validation_alias=AliasChoices("S3_ALLOWED_UPLOAD_CONTENT_TYPES"),
    )

    # --- Resume processing (disabled unless explicitly configured) ---
    resume_processing_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("RESUME_PROCESSING_ENABLED")
    )
    resume_max_upload_bytes: int = Field(
        default=10_000_000, ge=1024, le=50_000_000, validation_alias=AliasChoices("RESUME_MAX_UPLOAD_BYTES")
    )
    resume_max_retries: int = Field(default=3, ge=0, le=5, validation_alias=AliasChoices("RESUME_MAX_RETRIES"))
    resume_retention_days: int = Field(default=30, ge=1, le=365, validation_alias=AliasChoices("RESUME_RETENTION_DAYS"))
    bedrock_model_id: str | None = Field(default=None, validation_alias=AliasChoices("BEDROCK_MODEL_ID"))
    resume_parser_provider: str = Field(default="nova", validation_alias=AliasChoices("RESUME_PARSER_PROVIDER"))
    bedrock_timeout_seconds: int = Field(default=60, ge=5, le=300, validation_alias=AliasChoices("BEDROCK_TIMEOUT_SECONDS"))
    textract_timeout_seconds: int = Field(default=180, ge=30, le=600, validation_alias=AliasChoices("TEXTRACT_TIMEOUT_SECONDS"))
    resume_parser_schema_version: str = Field(
        default="1",
        validation_alias=AliasChoices("RESUME_PARSER_SCHEMA_VERSION", "BEDROCK_SCHEMA_VERSION"),
    )

    # --- Google OAuth ---
    google_client_id: str | None = Field(default=None, validation_alias=AliasChoices("GOOGLE_CLIENT_ID"))
    google_client_secret: str | None = Field(default=None, validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET"))
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/google/callback",
        validation_alias=AliasChoices("GOOGLE_REDIRECT_URI"),
    )

    # --- LinkedIn OAuth ---
    linkedin_client_id: str | None = Field(default=None, validation_alias=AliasChoices("LINKEDIN_CLIENT_ID"))
    linkedin_client_secret: str | None = Field(default=None, validation_alias=AliasChoices("LINKEDIN_CLIENT_SECRET"))
    linkedin_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/linkedin/callback",
        validation_alias=AliasChoices("LINKEDIN_REDIRECT_URI"),
    )

    # --- GitHub OAuth ---
    github_client_id: str | None = Field(default=None, validation_alias=AliasChoices("GITHUB_CLIENT_ID"))
    github_client_secret: str | None = Field(default=None, validation_alias=AliasChoices("GITHUB_CLIENT_SECRET"))
    github_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/github/callback",
        validation_alias=AliasChoices("GITHUB_REDIRECT_URI"),
    )

    # --- HTTP / CORS ---
    cors_origins: list[str] = Field(default_factory=list, validation_alias=AliasChoices("CORS_ORIGINS"))
    cors_allow_credentials: bool = Field(default=False, validation_alias=AliasChoices("CORS_ALLOW_CREDENTIALS"))

    # --- Security surface ---
    docs_enabled: bool = Field(default=True, validation_alias=AliasChoices("DOCS_ENABLED"))
    trusted_hosts: list[str] = Field(
        default_factory=list,
        description="If non-empty, enable TrustedHostMiddleware with these hostnames",
        validation_alias=AliasChoices("TRUSTED_HOSTS"),
    )

    @field_validator("database_url")
    @classmethod
    def validate_async_pg_url(cls, v: str) -> str:
        lowered = v.lower()
        if "+asyncpg" not in lowered and "asyncpg" not in lowered:
            msg = "database_url must use asyncpg driver, e.g. postgresql+asyncpg://..."
            raise ValueError(msg)
        return v

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("email_backend")
    @classmethod
    def normalize_email_backend(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("job_backend")
    @classmethod
    def normalize_job_backend(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("resume_parser_provider")
    @classmethod
    def normalize_resume_parser_provider(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("phone_otp_backend")
    @classmethod
    def normalize_phone_otp_backend(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, v: object) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        """Accept JSON array from some orchestrators or comma-separated string."""

        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                import json

                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in raw.split(",") if part.strip()]
        return []

    @field_validator("s3_allowed_upload_content_types", mode="before")
    @classmethod
    def parse_allowed_upload_content_types(cls, v: object) -> list[str]:
        defaults = [
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
        if v is None or v == "":
            return defaults
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                import json

                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in raw.split(",") if part.strip()]
        return defaults

    @field_validator("s3_allowed_upload_content_types")
    @classmethod
    def normalize_allowed_upload_content_types(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for entry in v:
            primary = entry.split(";")[0].strip().lower()
            if primary:
                cleaned.append(primary)
        if not cleaned:
            msg = "s3_allowed_upload_content_types must contain at least one MIME type"
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def enforce_production_hardening(self) -> Self:
        """Stricter checks when APP_ENV=production."""

        weights_total = (
            self.trust_score_identity_weight
            + self.trust_score_employment_weight
            + self.trust_score_education_weight
        )
        if not isclose(weights_total, 1.0, abs_tol=1e-6):
            raise ValueError("TRUST_SCORE_*_WEIGHT values must sum to exactly 1.0")

        if self.app_env == AppEnvironment.PRODUCTION:
            if len(self.jwt_secret_key) < 48:
                msg = "JWT_SECRET_KEY must be at least 48 characters in APP_ENV=production."
                raise ValueError(msg)
            if self.email_backend == "console":
                msg = "EMAIL_BACKEND must be smtp or ses in APP_ENV=production."
                raise ValueError(msg)
            if self.phone_otp_enabled and self.phone_otp_backend == "console":
                msg = "PHONE_OTP_BACKEND must not be console in APP_ENV=production when PHONE_OTP_ENABLED=true."
                raise ValueError(msg)
            if self.phone_otp_backend == "staging_fixed":
                msg = "PHONE_OTP_BACKEND=staging_fixed is forbidden in APP_ENV=production."
                raise ValueError(msg)

        if self.phone_otp_backend == "staging_fixed":
            if self.app_env != AppEnvironment.STAGING:
                msg = "PHONE_OTP_BACKEND=staging_fixed requires APP_ENV=staging."
                raise ValueError(msg)
            code = self.staging_phone_otp_code.get_secret_value() if self.staging_phone_otp_code else ""
            if not re.fullmatch(r"\d{6}", code):
                msg = "STAGING_PHONE_OTP_CODE must contain exactly six digits."
                raise ValueError(msg)
        if self.email_backend == "smtp":
            if not self.smtp_host:
                msg = "SMTP_HOST is required when EMAIL_BACKEND=smtp."
                raise ValueError(msg)
            if self.smtp_use_ssl and self.smtp_use_tls:
                msg = "Set only one of SMTP_USE_SSL (465) or SMTP_USE_TLS (587), not both."
                raise ValueError(msg)

        if self.email_backend == "ses":
            if not self.aws_region:
                msg = "AWS_REGION is required when EMAIL_BACKEND=ses."
                raise ValueError(msg)
            if not self.ses_from_email:
                msg = "SES_FROM_EMAIL is required when EMAIL_BACKEND=ses."
                raise ValueError(msg)

        if self.email_backend not in {"console", "smtp", "ses"}:
            msg = "EMAIL_BACKEND must be one of: console, smtp, ses."
            raise ValueError(msg)

        if self.phone_otp_backend not in {"console", "staging_fixed", "real_provider_placeholder"}:
            msg = "PHONE_OTP_BACKEND must be one of: console, staging_fixed, real_provider_placeholder."
            raise ValueError(msg)

        if self.resume_processing_enabled:
            if self.resume_parser_provider not in {"nova", "anthropic"}:
                raise ValueError("RESUME_PARSER_PROVIDER must be nova or anthropic")
            missing = []
            if not self.aws_region:
                missing.append("AWS_REGION")
            if not self.s3_documents_bucket:
                missing.append("S3_DOCUMENTS_BUCKET")
            if not self.bedrock_model_id:
                missing.append("BEDROCK_MODEL_ID")
            if self.job_backend == "sqs" and not self.sqs_main_queue_url:
                missing.append("SQS_MAIN_QUEUE_URL")
            if missing:
                raise ValueError("Resume processing requires: " + ", ".join(missing))

        if self.job_backend not in {"inline", "sqs"}:
            msg = "JOB_BACKEND must be one of: inline, sqs."
            raise ValueError(msg)

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnvironment.PRODUCTION

    @property
    def cors_effective_allow_credentials(self) -> bool:
        """Browsers forbid credentials with wildcard or empty-origin CORS."""

        if not self.cors_origins or self.cors_origins == ["*"]:
            return False
        return self.cors_allow_credentials


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton — call `reload_settings()` when env vars change (e.g. tests)."""

    return Settings()


def reload_settings() -> None:
    """Clear the settings cache."""

    get_settings.cache_clear()
