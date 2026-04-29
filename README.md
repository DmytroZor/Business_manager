# Business Manage System API

Backend API for a small business delivery workflow built with FastAPI, SQLAlchemy (async), and PostgreSQL.

## Features

- User registration and JWT authentication
- Telegram account linking for existing users
- Product catalog listing and management
- Customer delivery address management
- Order creation with item snapshots and totals
- Courier delivery workflow with self-assignment and status updates
- Admin order workflows for courier assignment, phone orders, and cancellations
- Customer review endpoints for delivered or cancelled orders
- Alembic-based schema migrations
- Custom OpenAPI schema and structured error responses

## Tech Stack

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x (async)
- Alembic
- PostgreSQL
- Pydantic v2 / pydantic-settings

## Project Structure

- `main.py` - FastAPI app initialization and router registration
- `core/` - settings, DB session, SQLAlchemy models
- `routers/` - HTTP endpoints (Users, Products, Address, Orders, Deliveries, Reviews)
- `manage/schemas/` - request/response DTOs for API and Swagger
- `manage/services/` - business logic layer
- `manage/docs/` - endpoint descriptions used in Swagger/OpenAPI
- `alembic/` - migration scripts and environment
- `tests/` - router, schema, service, and integration tests

## Domain Overview

The API models the full delivery workflow for a fish delivery business:

- `User` with role-based access (`customer`, `courier`, `admin`)
- `Customer` and `Courier` profiles
- `Address` records for customer delivery locations
- `Product` catalog entries
- `Order` and `OrderItem` snapshots
- `Delivery` records with assignment and lifecycle status
- `Payment` records in the data model for future payment tracking
- `Review` entries linked to orders and optional products

## Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME
JWT_SECRET=your_secret
JWT_ALGORITHM=HS256
JWT_EXPIRATION=3600
JWT_REFRESH_EXPIRATION=604800
```

## Local Setup

1. Create and activate virtual environment.
2. Install dependencies.
3. Apply migrations.
4. Run application.

Example (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
uvicorn main:app --reload
```

## API Documentation

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

The API includes endpoint-level summaries/descriptions and schema field descriptions for detailed Swagger documentation.

## Authentication

- Registration endpoint: `POST /users/register`
- Login endpoint: `POST /users/login`
- Login accepts email or phone number in the `username` field of OAuth2 form.
- For protected endpoints, authorize in Swagger with the returned bearer token.

## Main Endpoint Groups

- `Users`
  - `POST /users/register`
  - `POST /users/login`
  - `POST /users/me/telegram-link`
  - `GET /users/admin/couriers`
- `Products`
  - `GET /products/`
  - `GET /products/{product_id}`
  - `POST /products/`
  - `PUT /products/{product_id}`
- `Address`
  - `POST /address/`
  - `GET /address/`
  - `PUT /address/`
- `Orders`
  - `POST /orders/`
  - `GET /orders/`
  - `GET /orders/{order_id}`
  - `GET /orders/admin/orders`
  - `GET /orders/admin/orders/{order_id}`
  - `POST /orders/admin/phone-order`
  - `PATCH /orders/admin/orders/{order_id}/cancel`
- `Deliveries`
  - `POST /deliveries/orders/{order_id}`
  - `GET /deliveries/available-orders`
  - `POST /deliveries/orders/{order_id}/self-assign`
  - `GET /deliveries/my`
  - `GET /deliveries/{delivery_id}`
  - `PATCH /deliveries/{delivery_id}/pick-up`
  - `PATCH /deliveries/{delivery_id}/complete`
  - `PATCH /deliveries/{delivery_id}/fail`
- `Reviews`
  - `POST /reviews/orders/{order_id}`
  - `GET /reviews/my`

## Database Migrations

- Show current revision:

```powershell
python -m alembic current
```

- Show migration history:

```powershell
python -m alembic history
```

- Upgrade to latest:

```powershell
python -m alembic upgrade head
```

## Testing

The repository includes:

- router tests in `tests/api/routers/`
- schema and service unit tests in `tests/unit/`
- database-backed integration tests in `tests/integration/`

Run all tests:

```powershell
pytest
```

Run integration tests with a dedicated database:

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/business_manage_test"
pytest -m integration
```

## Error Handling

Services validate business rules and return explicit HTTP errors for common failures:

- `400` - invalid business input / missing profile
- `401` - unauthorized
- `404` - entity not found
- `409` - uniqueness conflict
- `422` - validation error
- `500` - unexpected database/internal errors

## Notes

- Timestamps are stored as timezone-aware values.
- Order creation is transactional and rolled back on failure.
- Address uniqueness is enforced at DB level per customer/location.
- Reviews can be created for delivered or cancelled orders.
- The API is used directly by the `Fish_Market_Bot` Telegram client.
