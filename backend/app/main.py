"""FastAPI application: error handling, middleware and route wiring."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.v1 import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.errors import DomainError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("estock")

DESCRIPTION = """
Shop management, inventory, sales, credit and online catalogue for Ethiopian
small and medium businesses.

Every operational endpoint is scoped to one business (tenant).  Authenticate
with `POST /api/v1/auth/register` or `/auth/login`, then send
`Authorization: Bearer <token>`.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="Estock API",
        description=DESCRIPTION,
        version="0.1.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Attach a request id and log how long each request took."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "%s %s %s %.1fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Some of the information provided is not valid",
                "details": [
                    {
                        "field": ".".join(str(part) for part in error["loc"][1:]),
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ],
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        # Unique and foreign-key constraints are the last line of defence for
        # duplicate postings; report them without leaking SQL.
        logger.warning("integrity_error path=%s detail=%s", request.url.path, exc)
        return JSONResponse(
            status_code=409,
            content={
                "code": "conflict",
                "message": "That change conflicts with existing data. Refresh and try again.",
            },
        )

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/health/ready", tags=["system"])
    def ready() -> dict:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
