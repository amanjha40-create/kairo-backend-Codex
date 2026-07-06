"""FastAPI application factory wiring middleware, routing, and observability primitives."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.db.session import dispose_engine
from app.infrastructure.redis import close_redis_client
from app.logging import setup_logging
from app.exceptions import AppException
from app.exceptions.handlers import (
    app_exception_handler,
    http_exception_handler,
    sqlalchemy_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.middleware.request_context import RequestContextMiddleware
from app.schemas.api_errors import ApiErrorResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup/shutdown hooks — logging configuration and pool disposal."""

    setup_logging()
    yield
    await dispose_engine()
    await close_redis_client()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        responses={
            401: {"model": ApiErrorResponse, "description": "Unauthorized"},
            403: {"model": ApiErrorResponse, "description": "Forbidden"},
            404: {"model": ApiErrorResponse, "description": "Not found"},
            409: {"model": ApiErrorResponse, "description": "Conflict"},
            422: {"model": ApiErrorResponse, "description": "Validation error"},
            429: {"model": ApiErrorResponse, "description": "Rate limited"},
            500: {"model": ApiErrorResponse, "description": "Internal server error"},
            503: {"model": ApiErrorResponse, "description": "Service unavailable"},
        },
    )

    application.add_exception_handler(AppException, app_exception_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    if settings.trusted_hosts:
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    origins = settings.cors_origins if settings.cors_origins else ["*"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=settings.cors_effective_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        result: dict[str, str] = {
            "service": settings.app_name,
            "health": f"{settings.api_v1_prefix}/health/live",
        }
        if settings.docs_enabled:
            result["docs"] = "/docs"
        return result

    return application


app = create_app()
