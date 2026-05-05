from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db import get_db
from core.models import Order, OrderStatus, Product, StockDocumentType, User, UserRole
from core.time_utils import kyiv_today
from core.settings import settings
from manage.schemas.auth_schema import AdminCourierCreate, AdminUserSummaryOut, phone_number_normalizer
from manage.schemas.delivery_schema import DeliveryAssignCreate
from manage.schemas.order_schema import (
    AdminOrderItemsUpdate,
    AdminOrderOut,
    AdminPhoneOrderCreate,
    OrderCancelPayload,
)
from manage.schemas.product_schema import (
    ActiveStatus,
    ProductCreate,
    ProductOut,
    ProductStockDocumentApply,
    ProductUpdate,
    SortField,
    SortOrder,
    StockStatus,
)
from manage.services import delivery_service, order_service, product_service
from manage.services.auth_service import create_access_token, create_courier_user_by_admin, decode_token, verify_password

from .presenters import (
    can_assign_order,
    can_cancel_order,
    can_edit_order_items,
    delivery_status_label,
    format_datetime,
    money,
    order_status_label,
    quantity,
)


ADMIN_DIR = Path(__file__).resolve().parent
ADMIN_STATIC_DIR = ADMIN_DIR / "static"
ADMIN_COOKIE_NAME = "bms_admin_token"
ADMIN_ORDERS_PAGE_SIZE = 10
ORDER_QUEUE_FILTER_OPTIONS = [
    ("", "All order queues"),
    ("active", "Active orders"),
    ("awaiting_courier", "Need courier"),
    ("with_courier", "With courier"),
    ("problem", "Problem cases"),
    ("completed", "Completed archive"),
]
ORDER_DATE_FILTER_OPTIONS = [
    ("", "All days"),
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("day_before_yesterday", "Day before yesterday"),
    ("today_yesterday", "Today + yesterday"),
    ("today_to_day_before_yesterday", "Today + yesterday + day before yesterday"),
    ("yesterday_day_before_yesterday", "Yesterday + day before yesterday"),
]
ORDER_CANCELLATION_REASON_OPTIONS = [
    ("Клієнт попросив скасувати замовлення", "Клієнт попросив скасувати замовлення"),
    ("Не вдалося зв’язатися з клієнтом", "Не вдалося зв’язатися з клієнтом"),
    ("Потрібно уточнити адресу або деталі доставки", "Потрібно уточнити адресу або деталі доставки"),
    ("Товару тимчасово немає в наявності", "Товару тимчасово немає в наявності"),
    ("Доставка на сьогодні недоступна", "Доставка на сьогодні недоступна"),
]
STOCK_DOCUMENT_TYPE_OPTIONS = [
    (StockDocumentType.RECEIPT.value, "Receipt"),
    (StockDocumentType.ADJUSTMENT.value, "Adjustment"),
    (StockDocumentType.INVENTORY_COUNT.value, "Inventory count"),
]

templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))
templates.env.filters["money"] = money
templates.env.filters["quantity"] = quantity
templates.env.filters["datetime"] = format_datetime
templates.env.filters["order_status"] = order_status_label
templates.env.filters["delivery_status"] = delivery_status_label

router = APIRouter(prefix="/admin", include_in_schema=False)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _url_for(request: Request, route_name: str, **params) -> str:
    clean_params = {
        key: value
        for key, value in params.items()
        if value not in (None, "", [])
    }
    base = str(request.url_for(route_name))
    if not clean_params:
        return base
    return f"{base}?{urlencode(clean_params)}"


def _parse_status_filter(raw_value: str | None) -> OrderStatus | None:
    if not raw_value:
        return None
    try:
        return OrderStatus(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid order status filter") from exc


def _parse_queue_filter(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    allowed_values = {value for value, _ in ORDER_QUEUE_FILTER_OPTIONS if value}
    if raw_value not in allowed_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid order queue filter")
    return raw_value


def _parse_date_filter(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    allowed_values = {value for value, _ in ORDER_DATE_FILTER_OPTIONS if value}
    if raw_value not in allowed_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid order day filter")
    return raw_value


def _parse_product_active_filter(raw_value: str | None) -> ActiveStatus:
    if not raw_value:
        return ActiveStatus.all_products
    try:
        return ActiveStatus(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product active filter") from exc


def _parse_product_stock_filter(raw_value: str | None) -> StockStatus:
    if not raw_value:
        return StockStatus.all_products
    try:
        return StockStatus(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product stock filter") from exc


def _parse_stock_document_type(raw_value: str | None) -> StockDocumentType:
    if not raw_value:
        return StockDocumentType.RECEIPT
    try:
        return StockDocumentType(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid stock document type") from exc


def _parse_optional_int(raw_value: str | None, *, field_name: str) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field_name}") from exc


def _parse_page(raw_value: str | int | None) -> int:
    if raw_value in (None, ""):
        return 1
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid page number") from exc
    return max(1, value)


def _order_to_dict(order) -> dict:
    return AdminOrderOut.model_validate(order_service.build_admin_order_payload(order)).model_dump()


def _courier_to_dict(user: User) -> dict:
    courier_profile = user.courier_profile
    return AdminUserSummaryOut(
        user_id=user.id,
        profile_id=courier_profile.id if courier_profile else None,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        telegram_id=user.telegram_id,
        role=user.role,
        is_active=user.is_active,
        vehicle_info=courier_profile.vehicle_info if courier_profile else None,
    ).model_dump()


def _product_to_dict(product) -> dict:
    return ProductOut.model_validate(product).model_dump()


def _stock_document_to_dict(document) -> dict:
    return {
        "id": document.id,
        "document_number": document.document_number,
        "document_type": document.document_type.value if hasattr(document.document_type, "value") else str(document.document_type),
        "document_date": document.document_date,
        "supplier_name": document.supplier.name if document.supplier is not None else None,
        "created_by_name": document.created_by_user.full_name if document.created_by_user is not None else None,
        "note": document.note,
        "created_at": document.created_at,
        "items": [
            {
                "id": item.id,
                "product_name": item.product_name,
                "unit": item.unit,
                "quantity_value": item.quantity_value,
                "applied_delta": item.applied_delta,
                "sale_unit_price": item.sale_unit_price,
                "purchase_unit_price": item.purchase_unit_price,
                "batch_code": item.batch_code,
                "serial_code": item.serial_code,
                "expires_at": item.expires_at,
                "note": item.note,
            }
            for item in document.items
        ],
    }


def _batch_to_dict(batch) -> dict:
    return {
        "id": batch.id,
        "batch_code": batch.batch_code,
        "serial_code": batch.serial_code,
        "expires_at": batch.expires_at,
        "purchase_unit_price": batch.purchase_unit_price,
        "original_quantity": batch.original_quantity,
        "available_quantity": batch.available_quantity,
        "received_at": batch.received_at,
        "note": batch.note,
        "supplier_name": batch.supplier.name if batch.supplier is not None else None,
        "document_number": batch.stock_document.document_number if batch.stock_document is not None else None,
        "document_type": (
            batch.stock_document.document_type.value
            if batch.stock_document is not None and hasattr(batch.stock_document.document_type, "value")
            else None
        ),
    }


async def _get_admin_user(request: Request, db: AsyncSession) -> User | None:
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None

    result = await db.execute(
        select(User)
        .options(selectinload(User.courier_profile))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if user.role != UserRole.ADMIN or not user.is_active:
        return None
    return user


async def _require_admin_user(request: Request, db: AsyncSession) -> User | RedirectResponse:
    user = await _get_admin_user(request, db)
    if user is None:
        return RedirectResponse(url=request.url_for("admin_login_page"), status_code=status.HTTP_303_SEE_OTHER)
    return user


async def _load_admin_couriers(db: AsyncSession, *, active_only: bool = True) -> list[dict]:
    stmt = (
        select(User)
        .options(selectinload(User.courier_profile))
        .where(User.role == UserRole.COURIER)
        .order_by(User.full_name.asc())
    )
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))

    result = await db.execute(stmt)
    return [_courier_to_dict(user) for user in result.scalars().all() if user.courier_profile is not None]


async def _load_active_products(db: AsyncSession) -> list:
    return await product_service.get_all_products(
        db,
        sort_field=SortField.name,
        active_status=ActiveStatus.active_products,
        sort_order=SortOrder.asc,
        offset=0,
        limit=200,
        stock_status=StockStatus.in_stock,
    )


async def _load_product_stats(db: AsyncSession) -> dict[str, int]:
    total = await db.scalar(select(func.count(Product.id)))
    active = await db.scalar(select(func.count(Product.id)).where(Product.is_active.is_(True)))
    inactive = await db.scalar(select(func.count(Product.id)).where(Product.is_active.is_(False)))
    in_stock = await db.scalar(select(func.count(Product.id)).where(Product.available_quantity > 0))
    out_of_stock = await db.scalar(select(func.count(Product.id)).where(Product.available_quantity <= 0))
    low_stock = await db.scalar(
        select(func.count(Product.id)).where(Product.available_quantity > 0, Product.available_quantity <= Decimal("5.000"))
    )
    return {
        "total": int(total or 0),
        "active": int(active or 0),
        "inactive": int(inactive or 0),
        "in_stock": int(in_stock or 0),
        "out_of_stock": int(out_of_stock or 0),
        "low_stock": int(low_stock or 0),
    }


async def _load_order_stats(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))
    counts = {row[0].value: row[1] for row in result.all()}
    counts["open"] = counts.get("placed", 0) + counts.get("preparing", 0) + counts.get("out_for_delivery", 0)
    return counts


def _template_context(request: Request, **extra) -> dict:
    return {
        "request": request,
        "order_status_options": [
            (order_status.value, order_status_label(order_status))
            for order_status in OrderStatus
        ],
        "order_queue_filter_options": ORDER_QUEUE_FILTER_OPTIONS,
        "order_date_filter_options": ORDER_DATE_FILTER_OPTIONS,
        "order_cancellation_reason_options": ORDER_CANCELLATION_REASON_OPTIONS,
        "can_assign_order": can_assign_order,
        "can_cancel_order": can_cancel_order,
        "can_edit_order_items": can_edit_order_items,
        **extra,
    }


async def _render_order_detail(
    request: Request,
    db: AsyncSession,
    *,
    order_id: int,
    admin_user: User,
    search: str = "",
    status_filter: str | None = None,
    queue_filter: str | None = None,
    date_filter: str | None = None,
    page: int = 1,
    message: str | None = None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    order = await order_service.get_order_for_admin(db, order_id)
    couriers = await _load_admin_couriers(db)
    return templates.TemplateResponse(
        "partials/order_detail.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="orders",
            order=_order_to_dict(order),
            couriers=couriers,
            search=search,
            status_filter=status_filter or "",
            queue_filter=queue_filter or "",
            date_filter=date_filter or "",
            page=page,
            selected_order_id=order_id,
            message=message,
            error=error,
        ),
        status_code=status_code,
    )


async def _render_products_page(
    request: Request,
    db: AsyncSession,
    *,
    admin_user: User,
    search: str,
    active_filter: ActiveStatus,
    stock_filter: StockStatus,
    selected_product_id: int | None = None,
    create_form_data: dict | None = None,
    edit_form_data: dict | None = None,
    stock_document_form_data: dict | None = None,
    stock_document_rows: list[dict] | None = None,
    stock_document_error: str | None = None,
    create_error: str | None = None,
    edit_error: str | None = None,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    products = await product_service.get_all_products(
        db,
        sort_field=SortField.name,
        active_status=active_filter,
        sort_order=SortOrder.asc,
        offset=0,
        limit=80,
        search=search,
        stock_status=stock_filter,
    )
    selected_product = None
    selected_product_batches: list[dict] = []
    if selected_product_id is not None:
        product = await product_service.get_product_by_id(db, selected_product_id)
        if product is not None:
            selected_product = _product_to_dict(product)
            selected_product_batches = [
                _batch_to_dict(batch)
                for batch in await product_service.get_product_batches(db, selected_product_id, limit=20)
            ]

    return templates.TemplateResponse(
        "products.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="products",
            stats=await _load_product_stats(db),
            products=[_product_to_dict(product) for product in products],
            stock_document_type_options=STOCK_DOCUMENT_TYPE_OPTIONS,
            recent_stock_documents=[
                _stock_document_to_dict(document)
                for document in await product_service.list_recent_stock_documents(db, limit=10)
            ],
            selected_product=selected_product,
            selected_product_batches=selected_product_batches,
            selected_product_id=selected_product_id,
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            create_form_data=create_form_data or {
                "name": "",
                "description": "",
                "image_url": "",
                "base_unit_price": "",
                "unit": "kg",
                "available_quantity": "0.000",
                "is_active": True,
            },
            edit_form_data=edit_form_data or {},
            stock_document_form_data=stock_document_form_data or _default_stock_document_form_data(),
            stock_document_rows=stock_document_rows or _empty_stock_document_rows(),
            stock_document_error=stock_document_error,
            create_error=create_error,
            edit_error=edit_error,
            message=message,
        ),
        status_code=status_code,
    )


def _parse_money(raw_value: str | None, *, default: str = "0.00") -> Decimal:
    text = (raw_value or default).strip()
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid money value") from exc


def _checkbox_value(raw_value) -> bool:
    return str(raw_value).lower() in {"1", "true", "on", "yes"}


def _build_product_form_data(form, *, include_missing: bool = True) -> dict:
    raw_data = {
        "name": str(form.get("name", "")).strip(),
        "description": str(form.get("description", "")).strip() or None,
        "image_url": str(form.get("image_url", "")).strip() or None,
        "base_unit_price": str(form.get("base_unit_price", "")).strip(),
        "unit": str(form.get("unit", "")).strip(),
        "available_quantity": str(form.get("available_quantity", "")).strip(),
        "is_active": _checkbox_value(form.get("is_active")),
    }
    if include_missing:
        return raw_data
    return {key: value for key, value in raw_data.items() if value != ""}


def _default_stock_document_form_data() -> dict:
    return {
        "document_type": StockDocumentType.RECEIPT.value,
        "document_number": "",
        "document_date": kyiv_today().isoformat(),
        "supplier_name": "",
        "supplier_phone": "",
        "supplier_email": "",
        "supplier_notes": "",
        "note": "",
    }


def _empty_stock_document_rows(count: int = 6) -> list[dict]:
    return [
        {
            "name": "",
            "unit": "kg",
            "sale_unit_price": "",
            "purchase_unit_price": "",
            "quantity_value": "",
            "batch_code": "",
            "serial_code": "",
            "expires_at": "",
            "note": "",
        }
        for _ in range(count)
    ]


def _stock_document_row_has_input(row: dict) -> bool:
    return any(
        str(row.get(field, "")).strip()
        for field in (
            "name",
            "sale_unit_price",
            "purchase_unit_price",
            "quantity_value",
            "batch_code",
            "serial_code",
            "expires_at",
            "note",
        )
    )


def _build_stock_document_rows(form) -> list[dict]:
    names = form.getlist("doc_name")
    units = form.getlist("doc_unit")
    sale_unit_prices = form.getlist("doc_sale_unit_price")
    purchase_unit_prices = form.getlist("doc_purchase_unit_price")
    quantity_values = form.getlist("doc_quantity_value")
    batch_codes = form.getlist("doc_batch_code")
    serial_codes = form.getlist("doc_serial_code")
    expires_at_values = form.getlist("doc_expires_at")
    notes = form.getlist("doc_note")

    rows: list[dict] = []
    for name, unit, sale_unit_price, purchase_unit_price, quantity_value, batch_code, serial_code, expires_at, note in zip(
        names,
        units,
        sale_unit_prices,
        purchase_unit_prices,
        quantity_values,
        batch_codes,
        serial_codes,
        expires_at_values,
        notes,
    ):
        row = {
            "name": str(name).strip(),
            "unit": str(unit).strip() or "kg",
            "sale_unit_price": str(sale_unit_price).strip(),
            "purchase_unit_price": str(purchase_unit_price).strip(),
            "quantity_value": str(quantity_value).strip(),
            "batch_code": str(batch_code).strip(),
            "serial_code": str(serial_code).strip(),
            "expires_at": str(expires_at).strip(),
            "note": str(note).strip(),
        }
        if not _stock_document_row_has_input(row):
            continue
        rows.append(row)

    if not rows:
        return _empty_stock_document_rows()

    rows.extend(_empty_stock_document_rows(max(0, 3 - len(rows))))
    return rows


@router.get("/", response_class=HTMLResponse, name="admin_root")
async def admin_root(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_admin_user(request, db)
    if user is None:
        return RedirectResponse(url=request.url_for("admin_login_page"), status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=request.url_for("admin_orders_dashboard"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse, name="admin_login_page")
async def admin_login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_admin_user(request, db)
    if user is not None:
        return RedirectResponse(url=request.url_for("admin_orders_dashboard"), status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "login.html",
        _template_context(request, admin_user=None, section="login", error=None),
    )


@router.post("/login", response_class=HTMLResponse, name="admin_login_action")
async def admin_login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_phone = None
    try:
        normalized_phone = phone_number_normalizer(username)
    except Exception:
        normalized_phone = None

    if normalized_phone:
        stmt = select(User).where((User.phone == normalized_phone) | (User.email == username))
    else:
        stmt = select(User).where((User.email == username) | (User.phone == username))

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    is_invalid = (
        user is None
        or user.hashed_password is None
        or not verify_password(password, user.hashed_password)
        or user.role != UserRole.ADMIN
        or not user.is_active
    )
    if is_invalid:
        return templates.TemplateResponse(
            "login.html",
            _template_context(
                request,
                admin_user=None,
                section="login",
                error="Invalid credentials or insufficient permissions.",
            ),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(url=request.url_for("admin_orders_dashboard"), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        httponly=True,
        max_age=settings.jwt_expiration,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout", name="admin_logout_action")
async def admin_logout_action():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return response


@router.get("/orders", response_class=HTMLResponse, name="admin_orders_dashboard")
async def admin_orders_dashboard(
    request: Request,
    search: str = Query(default=""),
    status_filter: str | None = Query(default=None),
    queue_filter: str | None = Query(default=None),
    date_filter: str | None = Query(default=None),
    selected_order_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    parsed_page = _parse_page(page)
    parsed_status_filter = _parse_status_filter(status_filter)
    parsed_queue_filter = _parse_queue_filter(queue_filter)
    parsed_date_filter = _parse_date_filter(date_filter)
    total_orders = await order_service.count_orders_for_admin(
        db,
        status_filter=parsed_status_filter,
        queue_filter=parsed_queue_filter,
        date_filter=parsed_date_filter,
        search=search,
    )
    total_pages = max(1, (total_orders + ADMIN_ORDERS_PAGE_SIZE - 1) // ADMIN_ORDERS_PAGE_SIZE)
    if parsed_page > total_pages:
        parsed_page = total_pages

    orders = await order_service.get_orders_for_admin(
        db,
        limit=ADMIN_ORDERS_PAGE_SIZE,
        offset=(parsed_page - 1) * ADMIN_ORDERS_PAGE_SIZE,
        status_filter=parsed_status_filter,
        queue_filter=parsed_queue_filter,
        date_filter=parsed_date_filter,
        search=search,
    )
    stats = await _load_order_stats(db)

    parsed_selected_order_id = _parse_optional_int(selected_order_id, field_name="selected order id")

    selected_order = None
    if parsed_selected_order_id is not None:
        try:
            selected_order = _order_to_dict(await order_service.get_order_for_admin(db, parsed_selected_order_id))
        except HTTPException:
            selected_order = None

    couriers = await _load_admin_couriers(db) if selected_order else []

    return templates.TemplateResponse(
        "orders.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="orders",
            stats=stats,
            orders=[_order_to_dict(order) for order in orders],
            order=selected_order,
            selected_order=selected_order,
            couriers=couriers,
            search=search,
            status_filter=status_filter or "",
            queue_filter=queue_filter or "",
            date_filter=date_filter or "",
            page=parsed_page,
            total_pages=total_pages,
            total_orders=total_orders,
            selected_order_id=parsed_selected_order_id,
        ),
    )


@router.get("/orders/table", response_class=HTMLResponse, name="admin_orders_table")
async def admin_orders_table(
    request: Request,
    search: str = Query(default=""),
    status_filter: str | None = Query(default=None),
    queue_filter: str | None = Query(default=None),
    date_filter: str | None = Query(default=None),
    selected_order_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    parsed_page = _parse_page(page)
    parsed_status_filter = _parse_status_filter(status_filter)
    parsed_queue_filter = _parse_queue_filter(queue_filter)
    parsed_date_filter = _parse_date_filter(date_filter)
    total_orders = await order_service.count_orders_for_admin(
        db,
        status_filter=parsed_status_filter,
        queue_filter=parsed_queue_filter,
        date_filter=parsed_date_filter,
        search=search,
    )
    total_pages = max(1, (total_orders + ADMIN_ORDERS_PAGE_SIZE - 1) // ADMIN_ORDERS_PAGE_SIZE)
    if parsed_page > total_pages:
        parsed_page = total_pages

    orders = await order_service.get_orders_for_admin(
        db,
        limit=ADMIN_ORDERS_PAGE_SIZE,
        offset=(parsed_page - 1) * ADMIN_ORDERS_PAGE_SIZE,
        status_filter=parsed_status_filter,
        queue_filter=parsed_queue_filter,
        date_filter=parsed_date_filter,
        search=search,
    )
    parsed_selected_order_id = _parse_optional_int(selected_order_id, field_name="selected order id")
    return templates.TemplateResponse(
        "partials/orders_table.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="orders",
            orders=[_order_to_dict(order) for order in orders],
            search=search,
            status_filter=status_filter or "",
            queue_filter=queue_filter or "",
            date_filter=date_filter or "",
            page=parsed_page,
            total_pages=total_pages,
            total_orders=total_orders,
            selected_order_id=parsed_selected_order_id,
        ),
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse, name="admin_order_detail")
async def admin_order_detail(
    request: Request,
    order_id: int,
    search: str = Query(default=""),
    status_filter: str | None = Query(default=None),
    queue_filter: str | None = Query(default=None),
    date_filter: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    if not _is_htmx(request):
        return RedirectResponse(
            url=_url_for(
                request,
                "admin_orders_dashboard",
                search=search,
                status_filter=status_filter,
                queue_filter=queue_filter,
                date_filter=date_filter,
                selected_order_id=order_id,
                page=page,
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return await _render_order_detail(
        request,
        db,
        order_id=order_id,
        admin_user=admin_user,
        search=search,
        status_filter=status_filter,
        queue_filter=queue_filter,
        date_filter=date_filter,
        page=page,
    )


@router.post("/orders/{order_id}/assign", response_class=HTMLResponse, name="admin_assign_order")
async def admin_assign_order(
    request: Request,
    order_id: int,
    courier_id: int = Form(...),
    fee: str = Form(default="0.00"),
    search: str = Form(default=""),
    status_filter: str | None = Form(default=None),
    queue_filter: str | None = Form(default=None),
    date_filter: str | None = Form(default=None),
    page: int = Form(default=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    try:
        payload = DeliveryAssignCreate(
            courier_id=courier_id,
            fee=_parse_money(fee),
        )
        await delivery_service.assign_delivery(
            db,
            order_id,
            payload,
            actor_user_id=admin_user.id,
            actor_role=admin_user.role,
            source="admin_panel",
        )
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            error=f"Could not assign courier: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if _is_htmx(request):
        response = await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            message="Courier assigned successfully.",
        )
        response.headers["HX-Trigger"] = "refresh-orders-list"
        return response

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_orders_dashboard",
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            selected_order_id=order_id,
            page=_parse_page(page),
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/orders/{order_id}/cancel", response_class=HTMLResponse, name="admin_cancel_order_web")
async def admin_cancel_order_web(
    request: Request,
    order_id: int,
    reason_code: str | None = Form(default=None),
    reason_note: str | None = Form(default=None),
    search: str = Form(default=""),
    status_filter: str | None = Form(default=None),
    queue_filter: str | None = Form(default=None),
    date_filter: str | None = Form(default=None),
    page: int = Form(default=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    selected_reason = (reason_code or "").strip()
    reason_note_value = (reason_note or "").strip()
    clean_reason = selected_reason or None
    if reason_note_value:
        clean_reason = f"{clean_reason}: {reason_note_value}" if clean_reason else reason_note_value

    try:
        await order_service.cancel_order_by_admin(
            db,
            order_id,
            payload=OrderCancelPayload(reason=clean_reason),
            actor_user_id=admin_user.id,
            actor_role=admin_user.role,
            source="admin_panel",
        )
    except HTTPException as exc:
        return await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            error=f"Could not cancel order: {exc.detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if _is_htmx(request):
        response = await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            message="Order cancelled successfully.",
        )
        response.headers["HX-Trigger"] = "refresh-orders-list"
        return response

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_orders_dashboard",
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            selected_order_id=order_id,
            page=_parse_page(page),
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/orders/{order_id}/items", response_class=HTMLResponse, name="admin_update_order_items")
async def admin_update_order_items(
    request: Request,
    order_id: int,
    search: str = Form(default=""),
    status_filter: str | None = Form(default=None),
    queue_filter: str | None = Form(default=None),
    date_filter: str | None = Form(default=None),
    page: int = Form(default=1),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    item_ids = form.getlist("item_id")
    quantities = form.getlist("quantity")
    items_payload = []
    for item_id, quantity_value in zip(item_ids, quantities):
        clean_item_id = str(item_id).strip()
        clean_quantity = str(quantity_value).strip()
        if not clean_item_id:
            continue
        items_payload.append({"item_id": clean_item_id, "quantity": clean_quantity or "0"})

    try:
        payload = AdminOrderItemsUpdate.model_validate({"items": items_payload})
        await order_service.update_order_items_by_admin(
            db,
            order_id,
            payload,
            actor_user_id=admin_user.id,
            actor_role=admin_user.role,
            source="admin_panel",
        )
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            error=f"Could not update order items: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if _is_htmx(request):
        response = await _render_order_detail(
            request,
            db,
            order_id=order_id,
            admin_user=admin_user,
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            page=_parse_page(page),
            message="Order items updated successfully.",
        )
        response.headers["HX-Trigger"] = "refresh-orders-list"
        return response

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_orders_dashboard",
            search=search,
            status_filter=status_filter,
            queue_filter=queue_filter,
            date_filter=date_filter,
            selected_order_id=order_id,
            page=_parse_page(page),
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/couriers", response_class=HTMLResponse, name="admin_couriers_page")
async def admin_couriers_page(
    request: Request,
    message: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    couriers = await _load_admin_couriers(db)
    return templates.TemplateResponse(
        "couriers.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="couriers",
            couriers=couriers,
            create_form_data={},
            create_error=None,
            message=message or None,
        ),
    )


@router.post("/couriers", response_class=HTMLResponse, name="admin_courier_create_action")
async def admin_courier_create_action(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    form_data = {
        "full_name": str(form.get("full_name", "")).strip(),
        "phone_number": str(form.get("phone_number", "")).strip(),
        "password": str(form.get("password", "")).strip(),
        "vehicle_info": str(form.get("vehicle_info", "")).strip() or None,
        "email": str(form.get("email", "")).strip() or None,
    }

    try:
        payload = AdminCourierCreate.model_validate(form_data)
        await create_courier_user_by_admin(db, payload)
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return templates.TemplateResponse(
            "couriers.html",
            _template_context(
                request,
                admin_user=admin_user,
                section="couriers",
                couriers=await _load_admin_couriers(db),
                create_form_data=form_data,
                create_error=f"Could not create courier: {detail}",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(request, "admin_couriers_page", message="Courier account created successfully."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/products", response_class=HTMLResponse, name="admin_products_page")
async def admin_products_page(
    request: Request,
    search: str = Query(default=""),
    active_filter: ActiveStatus = Query(default=ActiveStatus.all_products),
    stock_filter: StockStatus = Query(default=StockStatus.all_products),
    selected_product_id: str | None = Query(default=None),
    message: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    return await _render_products_page(
        request,
        db,
        admin_user=admin_user,
        search=search,
        active_filter=active_filter,
        stock_filter=stock_filter,
        selected_product_id=_parse_optional_int(selected_product_id, field_name="selected product id"),
        message=message or None,
    )


@router.post("/products", response_class=HTMLResponse, name="admin_product_create_action")
async def admin_product_create_action(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    search = str(form.get("search", "")).strip()
    active_filter = _parse_product_active_filter(str(form.get("active_filter", ActiveStatus.all_products.value)))
    stock_filter = _parse_product_stock_filter(str(form.get("stock_filter", StockStatus.all_products.value)))
    selected_product_id = _parse_optional_int(str(form.get("selected_product_id", "")).strip(), field_name="selected product id")
    form_data = _build_product_form_data(form, include_missing=True)

    try:
        payload = ProductCreate.model_validate(form_data)
        created_product = await product_service.create_product(db, payload)
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            selected_product_id=selected_product_id,
            create_form_data=form_data,
            create_error=f"Could not create product: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_products_page",
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            selected_product_id=created_product.id,
            message="Product created successfully.",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{product_id}", response_class=HTMLResponse, name="admin_product_update_action")
async def admin_product_update_action(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    search = str(form.get("search", "")).strip()
    active_filter = _parse_product_active_filter(str(form.get("active_filter", ActiveStatus.all_products.value)))
    stock_filter = _parse_product_stock_filter(str(form.get("stock_filter", StockStatus.all_products.value)))
    form_data = _build_product_form_data(form, include_missing=False)
    edit_form_data = _build_product_form_data(form, include_missing=True)

    try:
        payload = ProductUpdate.model_validate(form_data)
        updated_product = await product_service.product_update_by_id(db, product_id, payload)
        if updated_product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            selected_product_id=product_id,
            edit_form_data=edit_form_data,
            edit_error=f"Could not update product: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_products_page",
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            selected_product_id=product_id,
            message="Product updated successfully.",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/stock-sheet", response_class=HTMLResponse, name="admin_product_stock_sheet_action")
async def admin_product_stock_sheet_action(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    search = str(form.get("search", "")).strip()
    active_filter = _parse_product_active_filter(str(form.get("active_filter", ActiveStatus.all_products.value)))
    stock_filter = _parse_product_stock_filter(str(form.get("stock_filter", StockStatus.all_products.value)))
    selected_product_id = _parse_optional_int(str(form.get("selected_product_id", "")).strip(), field_name="selected product id")
    stock_document_form_data = {
        "document_type": str(form.get("document_type", StockDocumentType.RECEIPT.value)).strip(),
        "document_number": str(form.get("document_number", "")).strip(),
        "document_date": str(form.get("document_date", kyiv_today().isoformat())).strip(),
        "supplier_name": str(form.get("supplier_name", "")).strip(),
        "supplier_phone": str(form.get("supplier_phone", "")).strip(),
        "supplier_email": str(form.get("supplier_email", "")).strip(),
        "supplier_notes": str(form.get("supplier_notes", "")).strip(),
        "note": str(form.get("note", "")).strip(),
    }
    stock_document_rows = _build_stock_document_rows(form)
    populated_rows = [row for row in stock_document_rows if _stock_document_row_has_input(row)]
    incomplete_rows = [row for row in populated_rows if not row.get("name") or not row.get("quantity_value")]
    payload_rows = [row for row in populated_rows if row.get("name") and row.get("quantity_value")]

    if not payload_rows:
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            selected_product_id=selected_product_id,
            stock_document_form_data=stock_document_form_data,
            stock_document_rows=stock_document_rows,
            stock_document_error="Add at least one document row with a product name and quantity.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if incomplete_rows:
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            selected_product_id=selected_product_id,
            stock_document_form_data=stock_document_form_data,
            stock_document_rows=stock_document_rows,
            stock_document_error="Every filled document row must include both product name and quantity.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = ProductStockDocumentApply.model_validate(
            {
                **stock_document_form_data,
                "document_type": _parse_stock_document_type(stock_document_form_data["document_type"]),
                "items": payload_rows,
            }
        )
        result = await product_service.apply_stock_document(db, payload, actor_user_id=admin_user.id)
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            selected_product_id=selected_product_id,
            stock_document_form_data=stock_document_form_data,
            stock_document_rows=stock_document_rows,
            stock_document_error=f"Could not apply warehouse document: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    selected_after_apply = selected_product_id
    if selected_after_apply is None and result.touched_products:
        selected_after_apply = result.touched_products[0].id

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_products_page",
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            selected_product_id=selected_after_apply,
            message=(
                f"Warehouse document saved: created {result.created_count}, "
                f"updated {result.updated_count} product(s)."
            ),
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/phone-orders/new", response_class=HTMLResponse, name="admin_phone_order_page")
async def admin_phone_order_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    return templates.TemplateResponse(
        "phone_order.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="phone-order",
            products=await _load_active_products(db),
            form_data={},
            items=[{"product_id": "", "quantity": ""}],
            error=None,
        ),
    )


@router.post("/phone-orders", response_class=HTMLResponse, name="admin_phone_order_create")
async def admin_phone_order_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await request.form()
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    items = []
    for product_id, quantity_value in zip(product_ids, quantities):
        clean_product_id = str(product_id).strip()
        clean_quantity = str(quantity_value).strip()
        if not clean_product_id and not clean_quantity:
            continue
        items.append({"product_id": clean_product_id, "quantity": clean_quantity})

    payload_data = {
        "customer_full_name": str(form.get("customer_full_name", "")).strip(),
        "customer_phone_number": str(form.get("customer_phone_number", "")).strip(),
        "customer_email": str(form.get("customer_email", "")).strip() or None,
        "street": str(form.get("street", "")).strip(),
        "building": str(form.get("building", "")).strip(),
        "apartment": str(form.get("apartment", "")).strip() or None,
        "address_notes": str(form.get("address_notes", "")).strip() or None,
        "note": str(form.get("note", "")).strip() or None,
        "items": items,
    }

    try:
        payload = AdminPhoneOrderCreate.model_validate(payload_data)
        order = await order_service.create_phone_order_by_admin(
            db,
            payload,
            actor_user_id=admin_user.id,
            actor_role=admin_user.role,
            source="admin_panel",
        )
    except (HTTPException, ValidationError) as exc:
        error_text = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return templates.TemplateResponse(
            "phone_order.html",
            _template_context(
                request,
                admin_user=admin_user,
                section="phone-order",
                products=await _load_active_products(db),
                form_data=payload_data,
                items=items or [{"product_id": "", "quantity": ""}],
                error=f"Could not create phone order: {error_text}",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(request, "admin_orders_dashboard", selected_order_id=order.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
