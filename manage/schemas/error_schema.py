from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    timestamp: datetime = Field(..., description="UTC timestamp when the error occurred.")
    path: str = Field(..., description="Request path that produced the error.")
    status_code: int = Field(..., description="HTTP status code.")
    error: str = Field(..., description="HTTP reason phrase.")
    detail: Any = Field(..., description="Detailed error information.")
    error_code: str | None = Field(default=None, description="Optional machine-readable internal error code.")


class ValidationErrorResponse(ErrorResponse):
    detail: list[dict[str, Any]] = Field(..., description="Validation errors produced by request parsing.")
