import logging
import time

from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import models
from core.db import engine
from core.logging_config import request_id_var, request_method_var, request_path_var, setup_logging
from core.settings import settings
from manage.admin import ADMIN_STATIC_DIR, router as admin_router
from manage.schemas.error_schema import ErrorResponse, ValidationErrorResponse
from routers import (
    address_router,
    delivery_router,
    internal_notification_router,
    order_router,
    product_router,
    review_router,
    user_router,
)


setup_logging()
logger = logging.getLogger("bms.app")

tags_metadata = [
    {"name": "Users", "description": "User registration and authentication endpoints."},
    {"name": "Products", "description": "Product catalog management and browsing."},
    {"name": "Address", "description": "Customer delivery address management."},
    {"name": "Orders", "description": "Customer order creation and tracking."},
]

app = FastAPI(
    title="Business Manage System API",
    version="1.0.0",
    description="Async FastAPI backend",
    openapi_tags=tags_metadata,
)


def _bind_request_context(request: Request):
    return (
        request_id_var.set(getattr(request.state, "request_id", "-")),
        request_method_var.set(request.method),
        request_path_var.set(request.url.path),
    )


def _reset_request_context(tokens) -> None:
    request_id_var.reset(tokens[0])
    request_method_var.reset(tokens[1])
    request_path_var.reset(tokens[2])


def _error_payload(
    request: Request,
    *,
    status_code: int,
    error: str,
    detail,
    error_code: str | None,
) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": str(request.url.path),
        "status_code": status_code,
        "error": error,
        "detail": detail,
        "error_code": error_code,
        "request_id": getattr(request.state, "request_id", None),
    }


def _json_error_response(request: Request, *, status_code: int, payload: dict) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=payload)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex[:12]
    request.state.request_id = request_id

    request_id_token = request_id_var.set(request_id)
    request_method_token = request_method_var.set(request.method)
    request_path_token = request_path_var.set(request.url.path)

    start_time = time.perf_counter()
    logger.info("Request started")

    response = None
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.exception("Request failed with %s", exc.__class__.__name__)
        raise
    finally:
        duration = time.perf_counter() - start_time
        status_text = response.status_code if response is not None else "error"
        logger.info("Request finished status=%s duration=%.3fs", status_text, duration)
        if response is not None:
            response.headers["X-Request-ID"] = request_id
        request_id_var.reset(request_id_token)
        request_method_var.reset(request_method_token)
        request_path_var.reset(request_path_token)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=tags_metadata,
    )

    components = openapi_schema.setdefault("components", {}).setdefault("schemas", {})
    components["ErrorResponse"] = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    components["ValidationErrorResponse"] = ValidationErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )

    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue

            responses = operation.setdefault("responses", {})
            responses.setdefault(
                "500",
                {
                    "description": "Internal server error",
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                    },
                },
            )

            if "422" in responses:
                responses["422"] = {
                    "description": "Validation error",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ValidationErrorResponse"}
                        }
                    },
                }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

if Path(ADMIN_STATIC_DIR).exists():
    app.mount("/admin/static", StaticFiles(directory=ADMIN_STATIC_DIR), name="admin_static")


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


@app.on_event("startup")
async def on_startup():
    logger.info("Application startup")
    if settings.auto_create_tables:
        await init_models()
        logger.info("Database schema created via startup hook")
    else:
        logger.info("Automatic create_all() is disabled; expecting Alembic-managed schema")


@app.get("/")
async def root():
    return {"status": "ok"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    tokens = _bind_request_context(request)
    try:
        logger.warning("HTTP %s: %s", exc.status_code, exc.detail)
    finally:
        _reset_request_context(tokens)

    reason = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus._value2member_map_ else "HTTP Error"
    payload = _error_payload(
        request,
        status_code=exc.status_code,
        error=reason,
        detail=exc.detail,
        error_code=None,
    )
    return _json_error_response(request, status_code=exc.status_code, payload=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    tokens = _bind_request_context(request)
    try:
        logger.warning("Validation error: %s", exc.errors())
    finally:
        _reset_request_context(tokens)

    payload = _error_payload(
        request,
        status_code=422,
        error="Unprocessable Entity",
        detail=exc.errors(),
        error_code="VALIDATION_ERROR",
    )
    return _json_error_response(request, status_code=422, payload=payload)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    tokens = _bind_request_context(request)
    try:
        logger.exception("Unhandled SQLAlchemy error: %s", exc.__class__.__name__)
    finally:
        _reset_request_context(tokens)

    payload = _error_payload(
        request,
        status_code=500,
        error="Internal Server Error",
        detail="Сталася помилка під час роботи з даними. Спробуйте повторити дію пізніше.",
        error_code="DATABASE_ERROR",
    )
    return _json_error_response(request, status_code=500, payload=payload)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tokens = _bind_request_context(request)
    try:
        logger.exception("Unhandled application error: %s", exc.__class__.__name__)
    finally:
        _reset_request_context(tokens)

    payload = _error_payload(
        request,
        status_code=500,
        error="Internal Server Error",
        detail="Внутрішня помилка сервера.",
        error_code="UNHANDLED_EXCEPTION",
    )
    return _json_error_response(request, status_code=500, payload=payload)


app.include_router(admin_router)
app.include_router(product_router.router)
app.include_router(user_router.router)
app.include_router(address_router.router)
app.include_router(order_router.router)
app.include_router(delivery_router.router)
app.include_router(review_router.router)
app.include_router(internal_notification_router.router)
