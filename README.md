# Business Manage System API

Backend API for a small business delivery workflow built with FastAPI, SQLAlchemy (async), and PostgreSQL.

## Features

- User registration and JWT authentication
- Product catalog listing and management
- Customer delivery address management
- Order creation with item snapshots and totals
- Alembic-based schema migrations

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
- `routers/` - HTTP endpoints (Users, Products, Address, Orders)
- `manage/schemas/` - request/response DTOs for API and Swagger
- `manage/services/` - business logic layer
- `alembic/` - migration scripts and environment

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

- `Users` - register/login/auth context
- `Products` - create, update, list, get by id
- `Address` - create, fetch, update customer addresses
- `Orders` - create order, get by id, list my orders

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
