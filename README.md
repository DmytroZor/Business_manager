# Business Manage System

Backend and management panel for a small-business order, warehouse, and delivery workflow. The system is built around FastAPI, async SQLAlchemy, and PostgreSQL, and serves as the source of truth for products, stock, orders, couriers, invoices, analytics, and Telegram-facing notifications.

This project powers:
- the public operational API used by `Fish_Market_Bot`;
- the web-based management panel for orders, products, couriers, invoices, and analytics;
- warehouse document processing through invoices;
- delivery lifecycle management and event logging.

## What the System Covers

`BusinessManageSystem` is designed for a delivery business with:
- one or more managers working in a browser-based management panel;
- customers placing orders through a social platform interface;
- couriers working from Telegram;
- stock updates handled through invoices and product batches.

## Core Features

### Accounts and access
- JWT-based authentication
- Roles: `customer`, `courier`, `admin`
- Telegram account linking for existing users
- Separate browser login flow for the management panel

### Orders and delivery
- Product catalog endpoints
- Delivery address management
- Order creation with transactional stock validation
- Phone order creation from the management panel
- Courier self-assignment and delivery status workflow
- Cancellation flow with manager reasons
- Order event log for status changes and operational timeline

### Inventory and warehouse
- Product management with price, stock, SKU, and availability
- Product deletion with a required reason
- Invoice-based stock updates
- Supplier references
- Product batch tracking
- Reserved vs available stock tracking
- Last purchase date and purchase price tracking

### Management panel
- Orders dashboard with filters, pagination, and detailed order view
- Products page with filters, stock corrections, and batch traceability
- Couriers page for creating courier accounts
- Phone order page for manager-created orders
- Invoice list and invoice creation as separate screens
- Product sales analytics page
- Global UI language switch for panel pages

### Notifications and auditability
- Internal Telegram notification queue
- Customer and courier status notifications
- Event log for order and delivery state transitions
- Structured logging and centralized error handling

## Tech Stack

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x (async)
- PostgreSQL
- Alembic
- Pydantic v2 / `pydantic-settings`
- Jinja2 templates
- JWT authentication

## Architecture Overview

The backend follows a layered architecture:

- `routers/` expose HTTP endpoints
- `manage/schemas/` define validated DTOs
- `manage/services/` contain business logic
- `core/models.py` defines SQLAlchemy models
- PostgreSQL stores the transactional state

Key service modules:
- `auth_service.py`
- `product_service.py`
- `inventory_service.py`
- `order_service.py`
- `delivery_service.py`
- `notification_service.py`
- `order_event_service.py`
- `analytics_service.py`

## Project Structure

- `main.py` - FastAPI app initialization, middleware, exception handlers, router registration
- `core/` - settings, DB session, models, logging config, time helpers
- `routers/` - HTTP API endpoints
- `manage/admin/` - management panel routes, templates, static assets, xlsx export
- `manage/schemas/` - request/response schemas
- `manage/services/` - business logic layer
- `manage/docs/` - OpenAPI descriptions
- `alembic/` - migration scripts and environment
- `scripts/seed_demo_data.py` - helper to populate demo products, phone orders, couriers, and invoices
- `tests/` - router, unit, smoke, and integration tests

## Domain Overview

The backend models the full operational workflow.

### Main entities
- `User` - base account record
- `Customer` - customer profile
- `Courier` - courier profile
- `Address` - delivery address
- `Product` - catalog item with available and reserved stock
- `Supplier` - product supplier
- `StockDocument` - warehouse invoice document
- `StockDocumentItem` - invoice line
- `ProductBatch` - tracked stock batch
- `Order` - order header
- `OrderItem` - order line snapshot
- `Delivery` - courier delivery lifecycle
- `Payment` - reserved for payment tracking
- `Review` - customer product/order review
- `NotificationDelivery` - internal notification outbox
- `OrderEventLog` - order and delivery event timeline

### Why these tables matter
- `Product`, `StockDocument`, and `ProductBatch` implement stock control and warehouse traceability.
- `Order`, `OrderItem`, and `Delivery` implement the customer-to-courier workflow.
- `NotificationDelivery` decouples Telegram delivery from transactional order creation.
- `OrderEventLog` records operational changes for audit and UI timelines.

## Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME
JWT_SECRET=your_secret
JWT_ALGORITHM=HS256
JWT_EXPIRATION=3600
JWT_REFRESH_EXPIRATION=604800
INTERNAL_API_TOKEN=your_internal_token
```

Important notes:
- `DATABASE_URL` should point to PostgreSQL
- `INTERNAL_API_TOKEN` must match the bot configuration
- on Windows or fresh server images, make sure `tzdata` is available because the project formats Kyiv timezone explicitly

## Local Setup

### 1. Create and activate a virtual environment

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Apply database migrations

```powershell
python -m alembic upgrade head
```

### 4. Run the application

```powershell
uvicorn main:app --reload
```

Default local URLs:
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Management panel login: `http://127.0.0.1:8000/admin/login`

## Management Panel Pages

The web panel currently includes:
- `/admin/orders`
- `/admin/products`
- `/admin/couriers`
- `/admin/phone-orders/new`
- `/admin/stock-documents`
- `/admin/stock-documents/new`
- `/admin/analytics/products`

## Main API Groups

### Users
- registration
- login
- Telegram linking
- admin courier listing

### Products
- product list
- product detail
- product create/update

### Address
- create/list/update customer addresses

### Orders
- customer order create/list/detail
- admin order list/detail
- phone order create
- order item updates
- order cancellation

### Deliveries
- available orders
- self-assign
- my deliveries
- pick up
- complete
- fail

### Reviews
- create review
- list own reviews

### Internal notifications
- claim pending Telegram notifications
- acknowledge sent/failed deliveries

## Database Migrations

Show current revision:

```powershell
python -m alembic current
```

Show migration history:

```powershell
python -m alembic history
```

Upgrade to latest:

```powershell
python -m alembic upgrade head
```

## Demo Data

To populate the main database with demo products, orders, couriers, and invoices:

```powershell
python scripts\seed_demo_data.py
```

Use this only when you intentionally want demo operational data in the configured database.

## Testing

### Router and unit tests

```powershell
pytest tests/api/routers -q
pytest tests/unit -q
```

### Full test run

```powershell
pytest
```

### Integration tests

Integration tests require a dedicated database:

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/business_manage_test"
pytest -m integration
```

Do **not** point integration tests at the working database. They recreate schema state and are meant for isolated test environments only.

### Smoke tests

Read-only smoke tests can be used against a live database for quick verification:

```powershell
pytest tests/smoke -q
```

## Logging and Error Handling

The backend includes:
- request-aware logging configuration
- centralized exception handlers
- structured HTTP errors for validation, auth, not-found, conflict, and internal failures

This makes operational issues easier to trace from both API and management panel flows.

## Notes

- All displayed timestamps are formatted in the Kyiv timezone.
- Order creation is transactional and protected against overselling.
- Invoices and batches update warehouse state separately from sales flow.
- The management panel and API share the same business logic layer.
- The backend is the source of truth; the Telegram bot is a client of this system.
