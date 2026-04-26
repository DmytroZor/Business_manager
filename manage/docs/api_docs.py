"""Centralized OpenAPI docs metadata for routers.

This module keeps endpoint titles, descriptions, and standard response
documentation in one place to avoid duplication across router files.
"""

from manage.schemas.error_schema import ErrorResponse, ValidationErrorResponse

ERROR_RESPONSES = {
    "bad_request": {"model": ErrorResponse, "description": "Bad request. Business rule validation failed."},
    "unauthorized": {"model": ErrorResponse, "description": "Unauthorized. Missing or invalid bearer token."},
    "not_found": {"model": ErrorResponse, "description": "Resource not found."},
    "conflict": {"model": ErrorResponse, "description": "Conflict. Resource already exists or violates unique rule."},
    "validation": {"model": ValidationErrorResponse, "description": "Validation error in request params/body."},
    "internal": {"model": ErrorResponse, "description": "Internal server or database error."},
}


USER_DOCS = {
    "login": {
        "summary": "Authenticate User",
        "description": (
            "Authenticate by email or phone number and return a bearer access token. "
            "Use this token in the Authorization header for protected endpoints."
        ),
    },
    "register": {
        "summary": "Register User Account",
        "description": (
            "Create a new user profile and linked role entity (customer or courier). "
            "Returns created user info and an access token."
        ),
    },
    "telegram_link": {
        "summary": "Link Telegram Account",
        "description": (
            "Attach a Telegram user identifier to the authenticated account. "
            "Useful for Telegram bot login and reconnecting existing business users."
        ),
    },
}


PRODUCT_DOCS = {
    "get_by_id": {
        "summary": "Get Product By ID",
        "description": "Return one product by identifier.",
    },
    "list": {
        "summary": "List Products",
        "description": (
            "Return products with filtering by active state, sorting by field, "
            "and pagination using limit/offset."
        ),
    },
    "create": {
        "summary": "Create Product",
        "description": "Create a new product in catalog. Authentication is required.",
    },
    "update": {
        "summary": "Update Product",
        "description": "Update selected product fields by identifier. Authentication is required.",
    },
}


ADDRESS_DOCS = {
    "create": {
        "summary": "Create Delivery Address",
        "description": "Create a delivery address for the authenticated customer's profile.",
    },
    "get": {
        "summary": "Get Customer Address",
        "description": "Return one address for the authenticated customer.",
    },
    "update": {
        "summary": "Update Customer Address",
        "description": "Update existing address fields for the authenticated customer.",
    },
}


ORDER_DOCS = {
    "create": {
        "summary": "Create Order",
        "description": (
            "Create an order with one or more items. Product prices and names are "
            "snapshotted into order items at creation time."
        ),
    },
    "get_by_id": {
        "summary": "Get Order By ID",
        "description": "Return a single order that belongs to the authenticated customer.",
    },
    "list": {
        "summary": "List Customer Orders",
        "description": "Return paginated order history for the authenticated customer.",
    },
}
