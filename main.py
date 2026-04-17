from datetime import datetime, timezone
from http import HTTPStatus

from core.db import engine
from routers import product_router, user_router, address_router, order_router, delivery_router, review_router
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
from core import models
from manage.schemas.error_schema import ErrorResponse, ValidationErrorResponse

tags_metadata = [
    {
        "name": "Users",
        "description": "User registration and authentication endpoints.",
    },
    {
        "name": "Products",
        "description": "Product catalog management and browsing.",
    },
    {
        "name": "Address",
        "description": "Customer delivery address management.",
    },
    {
        "name": "Orders",
        "description": "Customer order creation and tracking.",
    },
]

app = FastAPI(
    title="Business Manage System API",
    version="1.0.0",
    description=(
        "Async FastAPI backend for user authentication, product catalog management, "
        "customer addresses, and order processing."
    ),
    contact={
        "name": "Business Manage System",
    },
    openapi_tags=tags_metadata,
)

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


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


@app.on_event("startup")
async def on_startup():
    await init_models()


@app.get("/", tags=["Users"], summary="API health endpoint", description="Simple endpoint to verify that the API is running.")
async def root():
    return {"status": "ok", "message": "Business Manage System API is running"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    reason = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus._value2member_map_ else "HTTP Error"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path),
            "status_code": exc.status_code,
            "error": reason,
            "detail": exc.detail,
            "error_code": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path),
            "status_code": 422,
            "error": "Unprocessable Entity",
            "detail": exc.errors(),
            "error_code": "VALIDATION_ERROR",
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=500,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path),
            "status_code": 500,
            "error": "Internal Server Error",
            "detail": "Database operation failed.",
            "error_code": "DATABASE_ERROR",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path),
            "status_code": 500,
            "error": "Internal Server Error",
            "detail": "Unexpected server error.",
            "error_code": "UNHANDLED_EXCEPTION",
        },
    )


app.include_router(product_router.router)
app.include_router(user_router.router)
app.include_router(address_router.router)
app.include_router(order_router.router)
app.include_router(delivery_router.router)
app.include_router(review_router.router)