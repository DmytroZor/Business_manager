from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
from manage.schemas.analytics_schema import SalesAnalyticsPeriod, SalesAnalyticsSort
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
from manage.services import analytics_service, delivery_service, order_service, product_service
from manage.services.auth_service import create_access_token, create_courier_user_by_admin, decode_token, verify_password

from .presenters import (
    can_assign_order,
    can_cancel_order,
    can_edit_order_items,
    delivery_status_label,
    delivery_status_label_for_lang,
    format_datetime,
    money,
    order_status_label,
    order_status_label_for_lang,
    quantity,
)
from .xlsx_export import build_xlsx_document


ADMIN_DIR = Path(__file__).resolve().parent
ADMIN_STATIC_DIR = ADMIN_DIR / "static"
ADMIN_COOKIE_NAME = "bms_admin_token"
ADMIN_UI_LANG_COOKIE_NAME = "bms_admin_lang"
ADMIN_ORDERS_PAGE_SIZE = 10
ADMIN_PRODUCTS_PAGE_SIZE = 10
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
STOCK_DOCUMENT_PERIOD_OPTIONS = [
    ("today", "Today"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("all", "All time"),
]
PRODUCT_CATEGORY_FILTER_OPTIONS = [
    ("all", "All product groups"),
    ("fish", "Fish"),
    ("seafood", "Seafood"),
    ("frozen", "Frozen"),
]
ORDER_CANCELLATION_REASON_OPTIONS = [
    ("Клієнт попросив скасувати замовлення", "Клієнт попросив скасувати замовлення"),
    ("Не вдалося зв’язатися з клієнтом", "Не вдалося зв’язатися з клієнтом"),
    ("Потрібно уточнити адресу або деталі доставки", "Потрібно уточнити адресу або деталі доставки"),
    ("Товару тимчасово немає в наявності", "Товару тимчасово немає в наявності"),
    ("Доставка на сьогодні недоступна", "Доставка на сьогодні недоступна"),
]
STOCK_DOCUMENT_FORM_TYPE = StockDocumentType.RECEIPT
SALES_ANALYTICS_PERIOD_OPTIONS = [
    (SalesAnalyticsPeriod.today.value, "Today"),
    (SalesAnalyticsPeriod.week.value, "Last 7 days"),
    (SalesAnalyticsPeriod.month.value, "Last 30 days"),
    (SalesAnalyticsPeriod.half_year.value, "Last 6 months"),
    (SalesAnalyticsPeriod.year.value, "Last 12 months"),
    (SalesAnalyticsPeriod.all_time.value, "All time"),
]
ORDER_CANCELLATION_REASON_OPTIONS_BY_LANG = {
    "en": [
        ("Customer requested cancellation", "Customer requested cancellation"),
        ("Could not reach the customer", "Could not reach the customer"),
        ("Delivery address or order details need clarification", "Delivery address or order details need clarification"),
        ("The product is temporarily unavailable", "The product is temporarily unavailable"),
        ("Delivery is unavailable for today", "Delivery is unavailable for today"),
    ],
    "uk": [
        ("Клієнт попросив скасувати замовлення", "Клієнт попросив скасувати замовлення"),
        ("Не вдалося зв’язатися з клієнтом", "Не вдалося зв’язатися з клієнтом"),
        ("Потрібно уточнити адресу або деталі доставки", "Потрібно уточнити адресу або деталі доставки"),
        ("Товару тимчасово немає в наявності", "Товару тимчасово немає в наявності"),
        ("Доставка на сьогодні недоступна", "Доставка на сьогодні недоступна"),
    ],
}
ORDER_QUEUE_FILTER_LABELS = {
    "en": {value: label for value, label in ORDER_QUEUE_FILTER_OPTIONS},
    "uk": {
        "": "Усі черги",
        "active": "Активні замовлення",
        "awaiting_courier": "Потрібен кур'єр",
        "with_courier": "Є кур'єр",
        "problem": "Проблемні випадки",
        "completed": "Завершений архів",
    },
}
ORDER_DATE_FILTER_LABELS = {
    "en": {value: label for value, label in ORDER_DATE_FILTER_OPTIONS},
    "uk": {
        "": "Усі дні",
        "today": "Сьогодні",
        "yesterday": "Учора",
        "day_before_yesterday": "Позавчора",
        "today_yesterday": "Сьогодні + учора",
        "today_to_day_before_yesterday": "Сьогодні + учора + позавчора",
        "yesterday_day_before_yesterday": "Учора + позавчора",
    },
}
PRODUCT_CATEGORY_FILTER_LABELS = {
    "en": {
        "all": "All product groups",
        "fish": "Fish",
        "seafood": "Seafood",
        "frozen": "Frozen",
    },
    "uk": {
        "all": "Усі групи товарів",
        "fish": "Риба",
        "seafood": "Морепродукти",
        "frozen": "Морожені",
    },
}
STOCK_DOCUMENT_PERIOD_LABELS = {
    "en": {
        "today": "Today",
        "7d": "Last 7 days",
        "30d": "Last 30 days",
        "all": "All time",
    },
    "uk": {
        "today": "Сьогодні",
        "7d": "Останні 7 днів",
        "30d": "Останні 30 днів",
        "all": "Увесь час",
    },
}
SALES_ANALYTICS_PERIOD_LABELS = {
    "en": {value: label for value, label in SALES_ANALYTICS_PERIOD_OPTIONS},
    "uk": {
        SalesAnalyticsPeriod.today.value: "Сьогодні",
        SalesAnalyticsPeriod.week.value: "Останні 7 днів",
        SalesAnalyticsPeriod.month.value: "Останні 30 днів",
        SalesAnalyticsPeriod.half_year.value: "Останні 6 місяців",
        SalesAnalyticsPeriod.year.value: "Останні 12 місяців",
        SalesAnalyticsPeriod.all_time.value: "Увесь час",
    },
}

ADMIN_BASE_TEXTS = {
    "en": {
        "brand_title": "Admin Console",
        "brand_copy": "Dispatch, phone orders, and order operations in one place.",
        "orders": "Orders",
        "phone_order": "Phone Order",
        "products": "Products",
        "stock_documents": "Invoices",
        "sales_analytics": "Sales Analytics",
        "couriers": "Couriers",
        "open_api_docs": "Open API Docs",
        "logout": "Log out",
    },
    "uk": {
        "brand_title": "Панель керування",
        "brand_copy": "Замовлення, телефонні заявки та операційна робота в одному місці.",
        "orders": "Замовлення",
        "phone_order": "Телефонне замовлення",
        "products": "Товари",
        "stock_documents": "Накладні",
        "sales_analytics": "Аналітика продажів",
        "couriers": "Кур'єри",
        "open_api_docs": "Документація API",
        "logout": "Вийти",
    },
}

STOCK_DOCUMENT_TEXTS = {
    "en": {
        "list_eyebrow": "Warehouse records",
        "list_title": "Invoices",
        "list_copy": "Review saved warehouse invoices, download them as Excel files, and switch to the entry form when you need to register a new delivery.",
        "create_eyebrow": "Warehouse intake",
        "create_title": "Create invoice",
        "create_copy": "Register today's delivery, select existing products when possible, and update stock from a clean dedicated form.",
        "open_create": "Create invoice",
        "open_list": "Back to invoices",
        "download_caption": "Click the invoice number to download an Excel file.",
        "language": "Language",
        "lang_uk": "Українська",
        "lang_en": "English",
        "document_number": "Document number",
        "document_date": "Document date",
        "supplier_name": "Supplier name",
        "supplier_phone": "Supplier phone",
        "supplier_email": "Supplier email",
        "supplier_notes": "Supplier notes",
        "document_note": "Document note",
        "supplier_name_placeholder": "Seafood Supplier LLC",
        "supplier_phone_placeholder": "+380...",
        "supplier_email_placeholder": "supply@example.com",
        "supplier_notes_placeholder": "Cold-chain delivery, morning slot, etc.",
        "document_note_placeholder": "Optional comment for this document",
        "existing_product": "Existing product",
        "sku": "SKU",
        "name": "Name",
        "unit": "Unit",
        "sell_price": "Sell price",
        "purchase_price": "Purchase price",
        "quantity": "Qty",
        "batch": "Batch",
        "serial": "Serial",
        "expires": "Expires",
        "note": "Note",
        "add_row": "Add row",
        "save": "Save invoice",
        "manual_new": "Manual / new product",
        "product_name_placeholder": "Salmon fillet",
        "unit_placeholder": "kg",
        "sale_price_placeholder": "390.00",
        "purchase_price_placeholder": "290.00",
        "quantity_placeholder": "+5.000 / -1.250 / 12.000",
        "batch_placeholder": "BATCH-001",
        "optional_placeholder": "Optional",
        "recent_title": "Recent invoices",
        "recent_copy": "Saved invoices with supplier information and line history.",
        "rows": "row(s)",
        "product": "Product",
        "input_qty": "Input qty",
        "applied_delta": "Applied delta",
        "purchase": "Purchase",
        "empty_title": "No invoices yet",
        "empty_copy": "The first saved invoice will appear here.",
        "no_rows_error": "Add at least one invoice row with a product name and quantity.",
        "incomplete_rows_error": "Every filled invoice row must include both product name and quantity.",
        "apply_error_prefix": "Could not save invoice",
        "saved_message": "Invoice saved: created {created}, updated {updated} product(s).",
        "download_sheet": "Invoice",
    },
    "uk": {
        "list_eyebrow": "Складські документи",
        "list_title": "Накладні",
        "list_copy": "Переглядайте збережені накладні, завантажуйте їх у форматі Excel і переходьте до окремої форми, коли потрібно занести нову поставку.",
        "create_eyebrow": "Приймання товару",
        "create_title": "Створення накладної",
        "create_copy": "Заносьте сьогоднішню поставку через окрему форму, обирайте наявні товари зі списку та оновлюйте склад без зайвого шуму на екрані.",
        "open_create": "Створити накладну",
        "open_list": "До списку накладних",
        "download_caption": "Натисніть на номер накладної, щоб завантажити її у форматі Excel.",
        "language": "Мова",
        "lang_uk": "Українська",
        "lang_en": "English",
        "document_number": "Номер документа",
        "document_date": "Дата документа",
        "supplier_name": "Постачальник",
        "supplier_phone": "Телефон постачальника",
        "supplier_email": "Email постачальника",
        "supplier_notes": "Примітки про постачальника",
        "document_note": "Примітка до документа",
        "supplier_name_placeholder": "ТОВ Морський постачальник",
        "supplier_phone_placeholder": "+380...",
        "supplier_email_placeholder": "supply@example.com",
        "supplier_notes_placeholder": "Холодний ланцюг, ранкова доставка тощо",
        "document_note_placeholder": "Необов'язковий коментар до накладної",
        "existing_product": "Наявний товар",
        "sku": "SKU",
        "name": "Назва",
        "unit": "Одиниця",
        "sell_price": "Ціна продажу",
        "purchase_price": "Закупівельна ціна",
        "quantity": "Кількість",
        "batch": "Партія",
        "serial": "Серія",
        "expires": "Термін придатності",
        "note": "Примітка",
        "add_row": "Додати рядок",
        "save": "Зберегти накладну",
        "manual_new": "Вручну / новий товар",
        "product_name_placeholder": "Філе лосося",
        "unit_placeholder": "кг",
        "sale_price_placeholder": "390.00",
        "purchase_price_placeholder": "290.00",
        "quantity_placeholder": "+5.000 / -1.250 / 12.000",
        "batch_placeholder": "BATCH-001",
        "optional_placeholder": "Необов'язково",
        "recent_title": "Останні накладні",
        "recent_copy": "Збережені накладні з постачальником та історією рядків.",
        "rows": "рядків",
        "product": "Товар",
        "input_qty": "Вхідна кількість",
        "applied_delta": "Застосована зміна",
        "purchase": "Закупівля",
        "empty_title": "Накладних ще немає",
        "empty_copy": "Перша збережена накладна з'явиться тут.",
        "no_rows_error": "Додайте хоча б один рядок накладної з назвою товару та кількістю.",
        "incomplete_rows_error": "Кожен заповнений рядок накладної має містити і назву товару, і кількість.",
        "apply_error_prefix": "Не вдалося зберегти накладну",
        "saved_message": "Накладну збережено: створено {created}, оновлено {updated} товарів.",
        "download_sheet": "Накладна",
    },
}
ADMIN_UI_TEXTS = {
    "en": {
        "language": "Language",
        "lang_uk": "Українська",
        "lang_en": "English",
        "login": {
            "eyebrow": "Private Access",
            "title": "Operations dashboard for the fish market team",
            "copy": "Use an administrator account from BusinessManageSystem to manage orders, dispatch couriers, and create phone orders from a browser.",
            "form_title": "Admin sign in",
            "form_copy": "Log in with email or phone number.",
            "identifier": "Identifier",
            "identifier_placeholder": "+380... or admin@example.com",
            "password": "Password",
            "password_placeholder": "Enter password",
            "submit": "Open control panel",
        },
        "orders": {
            "eyebrow": "Order operations",
            "title": "Orders and dispatch",
            "copy": "Review incoming orders, assign couriers, and handle problem cases from the browser.",
            "open": "Open",
            "placed": "Placed",
            "preparing": "Preparing",
            "out_for_delivery": "Out for delivery",
            "delivered": "Delivered",
            "cancelled": "Cancelled",
            "search": "Search",
            "search_placeholder": "Order ID, phone, name, email, street",
            "status": "Status",
            "queue_view": "Queue view",
            "placed_on": "Placed on",
            "apply": "Apply",
            "reset": "Reset",
            "queue": "Queue",
            "showing": "Showing",
            "of": "of",
            "matching_orders": "matching orders",
            "queue_page": "Queue page",
        },
        "orders_table": {
            "unknown_customer": "Unknown customer",
            "courier_not_assigned": "Courier not assigned",
            "previous_10": "Previous 10",
            "next_10": "Next 10",
            "queue_page": "Queue page",
            "no_orders_title": "No orders match the current filters",
            "no_orders_copy": "Try another status or a broader search query.",
        },
        "order_empty": {
            "eyebrow": "Select an order",
            "title": "Order details will appear here",
            "copy": "Choose an order from the queue to inspect the customer, items, delivery state, and available actions.",
        },
        "order_detail": {
            "eyebrow": "Order detail",
            "placed": "Placed",
            "customer": "Customer",
            "name": "Name",
            "phone": "Phone",
            "email": "Email",
            "unknown_customer": "Unknown customer",
            "delivery_address": "Delivery address",
            "street": "Street",
            "building": "Building",
            "apartment": "Apartment",
            "notes": "Notes",
            "no_delivery_address": "No delivery address available.",
            "items": "Items",
            "product": "Product",
            "quantity": "Quantity",
            "unit_price": "Unit price",
            "subtotal": "Subtotal",
            "update_item_quantities": "Update item quantities",
            "delivery": "Delivery",
            "fee": "Fee",
            "courier": "Courier",
            "assigned_at": "Assigned at",
            "picked_up_at": "Picked up at",
            "delivered_at": "Delivered at",
            "failure_reason": "Failure reason",
            "no_active_delivery": "No active delivery is attached to this order.",
            "actions": "Actions",
            "assign_courier": "Assign courier",
            "select_courier": "Select courier",
            "delivery_fee": "Delivery fee",
            "assign_courier_button": "Assign courier",
            "cancellation_reason": "Cancellation reason",
            "select_reason": "Select a reason",
            "manager_note": "Manager note",
            "manager_note_placeholder": "Optional extra details for the team",
            "cancel_order": "Cancel order",
            "no_actions": "No management actions are available for the current state of this order.",
            "status_timeline": "Status timeline",
            "system": "System",
            "order_label": "Order",
            "delivery_label": "Delivery",
            "event_recorded": "Event recorded",
        },
        "phone_order": {
            "eyebrow": "Phone order desk",
            "title": "Create a phone order",
            "copy": "Capture the customer, address, and items in one form. Customer-facing delivery messaging still explains that delivery takes place the next day.",
            "customer": "Customer",
            "customer_copy": "Used to link an existing customer or create a new one.",
            "full_name": "Full name",
            "phone_number": "Phone number",
            "email": "Email",
            "delivery_address": "Delivery address",
            "delivery_address_copy": "This address will be reused if the same customer and location already exist.",
            "street": "Street",
            "building": "Building",
            "apartment": "Apartment / office",
            "address_notes": "Address notes",
            "items": "Items",
            "items_copy": "Add one or more products with quantity. Use decimal quantities if needed.",
            "product": "Product",
            "select_product": "Select product",
            "quantity": "Quantity",
            "quantity_placeholder": "1 or 1.5",
            "remove": "Remove",
            "add_item": "Add another item",
            "order_note": "Order note",
            "order_note_copy": "Optional internal or customer note for the order.",
            "note": "Note",
            "submit": "Create phone order",
            "back": "Back to orders",
        },
        "products": {
            "eyebrow": "Warehouse and catalog",
            "title": "Products and stock overview",
            "copy": "Use this page for the live catalog, quick stock corrections, and batch traceability. Warehouse invoices live on a separate page.",
            "open_stock_documents": "Open invoices",
            "total": "Total",
            "active": "Active",
            "inactive": "Inactive",
            "free_stock": "Free stock",
            "low_stock": "Low stock",
            "out_of_stock": "Out of stock",
            "search": "Search",
            "search_placeholder": "Name, SKU, description",
            "status": "Status",
            "stock": "Stock",
            "all_products": "All products",
            "active_only": "Active",
            "inactive_only": "Inactive",
            "all_stock_states": "All stock states",
            "free_stock_available": "Free stock available",
            "low_free_stock": "Low free stock",
            "no_free_stock": "No free stock",
            "product_library": "Product library",
            "product_library_copy": "Pick a product to inspect stock, last purchase data, and batch history.",
            "no_image": "No image",
            "reserved": "Reserved",
            "on_hand": "On hand",
            "no_products_title": "No products match these filters",
            "no_products_copy": "Try a broader search or create a new catalog card.",
            "create_title": "Create product card",
            "create_copy": "Create a catalog card first if you want a clean public listing. Audited stock movement is handled through warehouse documents.",
            "name": "Name",
            "unit": "Unit",
            "selling_price": "Selling price",
            "initial_free_stock": "Initial free stock",
            "image_url": "Image URL",
            "description": "Description",
            "audit_note": "New stock receipts and corrections should be recorded from the invoices page so every movement stays in the audit trail.",
            "show_in_catalog": "Show product in the active catalog",
            "create_product": "Create product",
            "edit_title": "Edit product",
            "edit_copy": "Update the customer-facing card, selling price, and use a quick stock correction when the free quantity must change immediately.",
            "updated": "Updated",
            "current_free_stock": "Current free stock",
            "catalog_active": "Product is active in the customer catalog",
            "save_product": "Save product card",
            "quick_correction": "Quick stock correction",
            "quick_correction_copy": "Set the free stock target directly from the product card. The change will still be written as an adjustment document for audit history.",
            "target_free_stock": "Target free stock",
            "reason_note": "Reason / note",
            "reason_placeholder": "Manual correction, recount, damaged stock...",
            "apply_stock_correction": "Apply stock correction",
            "open_full_stock_documents": "Open full invoices",
            "batch_traceability": "Batch traceability",
            "batch_traceability_copy": "Physical stock that currently sits on the warehouse shelf.",
            "batch": "Batch",
            "serial": "Serial",
            "supplier": "Supplier",
            "purchase": "Purchase",
            "available": "Available",
            "original": "Original",
            "expires": "Expires",
            "document": "Document",
            "last_purchase_date": "Last purchase date",
            "last_purchase_price": "Last purchase price",
        },
        "couriers": {
            "eyebrow": "Courier roster",
            "title": "Active couriers",
            "copy": "Quick reference for assignment-ready couriers connected to the backend, plus a direct way to pre-create new courier accounts for Telegram login.",
            "create_title": "Create courier account",
            "create_copy": "Pre-create the courier in the backend so they can log in to Telegram later and link their Telegram ID to the existing account.",
            "full_name": "Full name",
            "phone": "Phone",
            "password": "Password",
            "vehicle_info": "Vehicle info",
            "vehicle_placeholder": "Car, bike, scooter",
            "email_optional": "Email (optional)",
            "submit": "Create courier",
            "active": "Active",
            "email": "Email",
            "vehicle": "Vehicle",
            "telegram": "Telegram",
            "not_specified": "Not specified",
            "not_linked": "Not linked",
            "empty_title": "No active couriers found",
            "empty_copy": "Create or activate courier accounts in the backend first.",
        },
        "analytics": {
            "eyebrow": "Sales visibility",
            "title": "Product sales analytics",
            "copy": "See which products move fastest, which ones lag behind, and how much revenue each item generates in the selected period.",
            "period": "Period",
            "sort_by": "Sort by",
            "rows": "Rows",
            "apply": "Apply",
            "unique_products": "Unique products sold",
            "total_quantity": "Total quantity",
            "revenue": "Revenue",
            "orders_included": "Orders included",
            "period_start": "Period start",
            "all_time": "All time",
            "generated": "Generated",
            "top_selling": "Top selling products",
            "top_selling_copy": "Sorted by the selected metric. Visual bars make it easier to spot the leaders quickly.",
            "orders": "orders",
            "quantity": "Quantity",
            "detailed_ranking": "Detailed ranking",
            "detailed_ranking_copy": "A sortable table for quick operational analysis and manual comparisons.",
            "product": "Product",
            "sku": "SKU",
            "unit": "Unit",
            "quantity_sold": "Quantity sold",
            "no_sales_title": "No sales in this period",
            "no_sales_copy": "Try a wider date range or check whether orders have already been created for the selected window.",
            "no_rows_title": "No rows yet",
            "no_rows_copy": "The first non-cancelled orders in this period will appear here.",
            "slowest": "Slowest movers",
            "slowest_copy": "The least active products within the same filtered dataset.",
            "not_enough_title": "Not enough sales yet",
            "not_enough_copy": "Once products start selling, the slower rows will show up here automatically.",
        },
    },
    "uk": {
        "language": "Мова",
        "lang_uk": "Українська",
        "lang_en": "English",
        "login": {
            "eyebrow": "Приватний доступ",
            "title": "Панель операційної роботи для команди рибного магазину",
            "copy": "Використовуйте обліковий запис адміністратора з BusinessManageSystem, щоб керувати замовленнями, призначати кур’єрів і оформлювати телефонні замовлення з браузера.",
            "form_title": "Вхід до панелі керування",
            "form_copy": "Увійдіть за email або номером телефону.",
            "identifier": "Ідентифікатор",
            "identifier_placeholder": "+380... або admin@example.com",
            "password": "Пароль",
            "password_placeholder": "Введіть пароль",
            "submit": "Відкрити панель керування",
        },
        "orders": {
            "eyebrow": "Керування замовленнями",
            "title": "Замовлення і доставка",
            "copy": "Переглядайте нові замовлення, призначайте кур’єрів і обробляйте проблемні ситуації з браузера.",
            "open": "Активні",
            "placed": "Оформлено",
            "preparing": "Готується",
            "out_for_delivery": "У доставці",
            "delivered": "Доставлено",
            "cancelled": "Скасовано",
            "search": "Пошук",
            "search_placeholder": "ID замовлення, телефон, ім’я, email, вулиця",
            "status": "Статус",
            "queue_view": "Черга",
            "placed_on": "Оформлено",
            "apply": "Застосувати",
            "reset": "Скинути",
            "queue": "Черга",
            "showing": "Показано",
            "of": "з",
            "matching_orders": "замовлень",
            "queue_page": "Сторінка черги",
        },
        "orders_table": {
            "unknown_customer": "Невідомий клієнт",
            "courier_not_assigned": "Кур’єра не призначено",
            "previous_10": "Попередні 10",
            "next_10": "Наступні 10",
            "queue_page": "Сторінка черги",
            "no_orders_title": "За поточними фільтрами замовлень немає",
            "no_orders_copy": "Спробуйте інший статус або ширший пошуковий запит.",
        },
        "order_empty": {
            "eyebrow": "Оберіть замовлення",
            "title": "Тут з’являться деталі замовлення",
            "copy": "Виберіть замовлення з черги, щоб переглянути клієнта, позиції, стан доставки та доступні дії.",
        },
        "order_detail": {
            "eyebrow": "Деталі замовлення",
            "placed": "Оформлено",
            "customer": "Клієнт",
            "name": "Ім’я",
            "phone": "Телефон",
            "email": "Email",
            "unknown_customer": "Невідомий клієнт",
            "delivery_address": "Адреса доставки",
            "street": "Вулиця",
            "building": "Будинок",
            "apartment": "Квартира",
            "notes": "Примітки",
            "no_delivery_address": "Адреса доставки відсутня.",
            "items": "Позиції",
            "product": "Товар",
            "quantity": "Кількість",
            "unit_price": "Ціна за одиницю",
            "subtotal": "Сума",
            "update_item_quantities": "Оновити кількість позицій",
            "delivery": "Доставка",
            "fee": "Вартість",
            "courier": "Кур’єр",
            "assigned_at": "Призначено",
            "picked_up_at": "Забрано",
            "delivered_at": "Доставлено",
            "failure_reason": "Причина збою",
            "no_active_delivery": "До цього замовлення не прив’язано активну доставку.",
            "actions": "Дії",
            "assign_courier": "Призначити кур’єра",
            "select_courier": "Оберіть кур’єра",
            "delivery_fee": "Вартість доставки",
            "assign_courier_button": "Призначити кур’єра",
            "cancellation_reason": "Причина скасування",
            "select_reason": "Оберіть причину",
            "manager_note": "Примітка менеджера",
            "manager_note_placeholder": "Додаткові деталі для команди",
            "cancel_order": "Скасувати замовлення",
            "no_actions": "Для поточного стану цього замовлення керуючі дії недоступні.",
            "status_timeline": "Історія статусів",
            "system": "Система",
            "order_label": "Замовлення",
            "delivery_label": "Доставка",
            "event_recorded": "Подію зафіксовано",
        },
        "phone_order": {
            "eyebrow": "Телефонні замовлення",
            "title": "Створення телефонного замовлення",
            "copy": "Занесіть клієнта, адресу й товари в одну форму. Для клієнта все одно залишиться повідомлення, що доставка відбувається наступного дня.",
            "customer": "Клієнт",
            "customer_copy": "Використовується для пошуку наявного клієнта або створення нового.",
            "full_name": "ПІБ",
            "phone_number": "Номер телефону",
            "email": "Email",
            "delivery_address": "Адреса доставки",
            "delivery_address_copy": "Ця адреса буде використана повторно, якщо для клієнта вже існує такий самий запис.",
            "street": "Вулиця",
            "building": "Будинок",
            "apartment": "Квартира / офіс",
            "address_notes": "Примітки до адреси",
            "items": "Позиції",
            "items_copy": "Додайте один або кілька товарів із кількістю. За потреби можна вказувати дробові значення.",
            "product": "Товар",
            "select_product": "Оберіть товар",
            "quantity": "Кількість",
            "quantity_placeholder": "1 або 1.5",
            "remove": "Прибрати",
            "add_item": "Додати ще товар",
            "order_note": "Примітка до замовлення",
            "order_note_copy": "Необов’язкова внутрішня або клієнтська примітка до замовлення.",
            "note": "Примітка",
            "submit": "Створити телефонне замовлення",
            "back": "Назад до замовлень",
        },
        "products": {
            "eyebrow": "Склад і каталог",
            "title": "Товари та залишки",
            "copy": "Ця сторінка потрібна для живого каталогу, швидких коригувань залишку та відстеження партій. Накладні ведуться на окремій сторінці.",
            "open_stock_documents": "Відкрити накладні",
            "total": "Усього",
            "active": "Активні",
            "inactive": "Неактивні",
            "free_stock": "Вільний залишок",
            "low_stock": "Малий залишок",
            "out_of_stock": "Немає в наявності",
            "search": "Пошук",
            "search_placeholder": "Назва, SKU, опис",
            "status": "Статус",
            "stock": "Залишок",
            "all_products": "Усі товари",
            "active_only": "Активні",
            "inactive_only": "Неактивні",
            "all_stock_states": "Усі стани залишку",
            "free_stock_available": "Є вільний залишок",
            "low_free_stock": "Мало вільного залишку",
            "no_free_stock": "Немає вільного залишку",
            "product_library": "Список товарів",
            "product_library_copy": "Оберіть товар, щоб переглянути залишки, останню закупівлю та партійну історію.",
            "no_image": "Немає зображення",
            "reserved": "У резерві",
            "on_hand": "Фізично на складі",
            "no_products_title": "За цими фільтрами товари не знайдено",
            "no_products_copy": "Спробуйте ширший пошук або створіть нову картку товару.",
            "create_title": "Створення картки товару",
            "create_copy": "Спочатку створіть картку товару для каталогу. Аудитований рух залишків ведеться через накладні.",
            "name": "Назва",
            "unit": "Одиниця",
            "selling_price": "Ціна продажу",
            "initial_free_stock": "Початковий вільний залишок",
            "image_url": "Посилання на зображення",
            "description": "Опис",
            "audit_note": "Приходи та коригування залишків потрібно вносити через сторінку накладних, щоб уся історія руху зберігалася в аудиті.",
            "show_in_catalog": "Показувати товар у активному каталозі",
            "create_product": "Створити товар",
            "edit_title": "Редагування товару",
            "edit_copy": "Оновіть картку для клієнта, ціну продажу та за потреби виконайте швидке коригування вільного залишку.",
            "updated": "Оновлено",
            "current_free_stock": "Поточний вільний залишок",
            "catalog_active": "Товар активний у клієнтському каталозі",
            "save_product": "Зберегти картку товару",
            "quick_correction": "Швидке коригування залишку",
            "quick_correction_copy": "Встановіть цільовий вільний залишок прямо з картки товару. Зміна все одно буде записана як окремий документ коригування.",
            "target_free_stock": "Цільовий вільний залишок",
            "reason_note": "Причина / примітка",
            "reason_placeholder": "Ручне коригування, перерахунок, списання пошкодженого товару...",
            "apply_stock_correction": "Застосувати коригування",
            "open_full_stock_documents": "Відкрити всі накладні",
            "batch_traceability": "Відстеження партій",
            "batch_traceability_copy": "Фізичний залишок, який зараз знаходиться на складі.",
            "batch": "Партія",
            "serial": "Серія",
            "supplier": "Постачальник",
            "purchase": "Закупівля",
            "available": "Доступно",
            "original": "Початково",
            "expires": "Термін придатності",
            "document": "Документ",
            "last_purchase_date": "Дата останньої закупівлі",
            "last_purchase_price": "Остання закупівельна ціна",
        },
        "couriers": {
            "eyebrow": "Команда кур’єрів",
            "title": "Активні кур’єри",
            "copy": "Швидкий довідник кур’єрів, готових до призначення, і зручне створення нових облікових записів для входу через Telegram.",
            "create_title": "Створення акаунта кур’єра",
            "create_copy": "Створіть кур’єра в бекенді заздалегідь, щоб потім він міг увійти через Telegram і прив’язати свій Telegram ID до наявного акаунта.",
            "full_name": "ПІБ",
            "phone": "Телефон",
            "password": "Пароль",
            "vehicle_info": "Транспорт",
            "vehicle_placeholder": "Авто, велосипед, скутер",
            "email_optional": "Email (необов’язково)",
            "submit": "Створити кур’єра",
            "active": "Активний",
            "email": "Email",
            "vehicle": "Транспорт",
            "telegram": "Telegram",
            "not_specified": "Не вказано",
            "not_linked": "Не прив’язано",
            "empty_title": "Активних кур’єрів не знайдено",
            "empty_copy": "Спочатку створіть або активуйте акаунти кур’єрів у бекенді.",
        },
        "analytics": {
            "eyebrow": "Аналітика продажів",
            "title": "Аналітика товарних продажів",
            "copy": "Переглядайте, які товари продаються найшвидше, які повільніше, і який дохід приносить кожна позиція за обраний період.",
            "period": "Період",
            "sort_by": "Сортувати за",
            "rows": "Рядків",
            "apply": "Застосувати",
            "unique_products": "Унікальних проданих товарів",
            "total_quantity": "Загальна кількість",
            "revenue": "Дохід",
            "orders_included": "Замовлень у звіті",
            "period_start": "Початок періоду",
            "all_time": "Увесь час",
            "generated": "Згенеровано",
            "top_selling": "Лідери продажів",
            "top_selling_copy": "Список відсортовано за обраною метрикою. Візуальні смуги допомагають швидко побачити лідерів.",
            "orders": "замовлень",
            "quantity": "Кількість",
            "detailed_ranking": "Детальний рейтинг",
            "detailed_ranking_copy": "Таблиця для швидкого операційного аналізу та ручних порівнянь.",
            "product": "Товар",
            "sku": "SKU",
            "unit": "Одиниця",
            "quantity_sold": "Продано",
            "no_sales_title": "У цьому періоді продажів немає",
            "no_sales_copy": "Спробуйте ширший діапазон дат або перевірте, чи вже були створені замовлення за цей період.",
            "no_rows_title": "Поки що без рядків",
            "no_rows_copy": "Перші нескасовані замовлення за цей період з’являться тут автоматично.",
            "slowest": "Найповільніші товари",
            "slowest_copy": "Найменш активні позиції в межах того самого відфільтрованого набору.",
            "not_enough_title": "Ще недостатньо продажів",
            "not_enough_copy": "Щойно товари почнуть продаватися, повільні позиції теж з’являться в цьому блоці.",
        },
    },
}
SALES_ANALYTICS_SORT_OPTIONS = [
    (SalesAnalyticsSort.quantity.value, "Quantity sold"),
    (SalesAnalyticsSort.revenue.value, "Revenue"),
    (SalesAnalyticsSort.order_count.value, "Orders"),
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


def _parse_product_category_filter(raw_value: str | None) -> str:
    normalized = (raw_value or "all").strip().lower()
    allowed_values = {value for value, _ in PRODUCT_CATEGORY_FILTER_OPTIONS}
    if normalized not in allowed_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid product category filter")
    return normalized


def _parse_stock_document_period(raw_value: str | None) -> str:
    normalized = (raw_value or "today").strip().lower()
    allowed_values = {value for value, _ in STOCK_DOCUMENT_PERIOD_OPTIONS}
    if normalized not in allowed_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid stock document period")
    return normalized


def _parse_stock_document_type(raw_value: str | None) -> StockDocumentType:
    if not raw_value:
        return StockDocumentType.RECEIPT
    try:
        return StockDocumentType(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid stock document type") from exc


def _parse_sales_period(raw_value: str | None) -> SalesAnalyticsPeriod:
    if not raw_value:
        return SalesAnalyticsPeriod.month
    try:
        return SalesAnalyticsPeriod(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid analytics period") from exc


def _parse_sales_sort(raw_value: str | None) -> SalesAnalyticsSort:
    if not raw_value:
        return SalesAnalyticsSort.quantity
    try:
        return SalesAnalyticsSort(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid analytics sort field") from exc


def _parse_ui_lang(raw_value: str | None) -> str:
    if not raw_value:
        return "uk"
    normalized = raw_value.strip().lower()
    if normalized not in {"uk", "en"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UI language")
    return normalized


def _resolve_ui_lang(request: Request, raw_value: str | None = None) -> str:
    if raw_value not in (None, ""):
        return _parse_ui_lang(raw_value)
    cookie_value = request.cookies.get(ADMIN_UI_LANG_COOKIE_NAME)
    if cookie_value:
        try:
            return _parse_ui_lang(cookie_value)
        except HTTPException:
            return "uk"
    return "uk"


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


def _current_relative_url(request: Request) -> str:
    relative = request.url.path
    if request.url.query:
        relative = f"{relative}?{request.url.query}"
    return relative


def _localized_option_pairs(labels_by_lang: dict[str, dict[str, str]], lang: str) -> list[tuple[str, str]]:
    labels = labels_by_lang.get(lang, labels_by_lang["en"])
    return list(labels.items())


def _stock_document_period_option_pairs(lang: str) -> list[tuple[str, str]]:
    labels = STOCK_DOCUMENT_PERIOD_LABELS.get(lang, STOCK_DOCUMENT_PERIOD_LABELS["en"])
    return [(value, labels[value]) for value, _ in STOCK_DOCUMENT_PERIOD_OPTIONS]


def _sales_period_option_pairs(lang: str) -> list[tuple[str, str]]:
    labels = SALES_ANALYTICS_PERIOD_LABELS.get(lang, SALES_ANALYTICS_PERIOD_LABELS["en"])
    return [(value, labels[value]) for value, _ in SALES_ANALYTICS_PERIOD_OPTIONS]


def _sales_sort_option_pairs(lang: str) -> list[tuple[str, str]]:
    labels = {
        "en": {
            SalesAnalyticsSort.quantity.value: "Quantity sold",
            SalesAnalyticsSort.revenue.value: "Revenue",
            SalesAnalyticsSort.order_count.value: "Orders",
        },
        "uk": {
            SalesAnalyticsSort.quantity.value: "Кількість продажів",
            SalesAnalyticsSort.revenue.value: "Дохід",
            SalesAnalyticsSort.order_count.value: "Замовлення",
        },
    }.get(lang)
    if labels is None:
        labels = {
            SalesAnalyticsSort.quantity.value: "Quantity sold",
            SalesAnalyticsSort.revenue.value: "Revenue",
            SalesAnalyticsSort.order_count.value: "Orders",
        }
    return [(value, labels[value]) for value, _ in SALES_ANALYTICS_SORT_OPTIONS]


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


def _product_reference_to_dict(product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "unit": product.unit,
        "base_unit_price": product.base_unit_price,
        "last_purchase_price": product.last_purchase_price,
        "available_quantity": product.available_quantity,
        "reserved_quantity": product.reserved_quantity,
        "stock_on_hand": product.stock_on_hand,
        "is_active": product.is_active,
    }


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
        "lines": [
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


async def _load_product_reference_options(db: AsyncSession) -> list[dict]:
    products = await product_service.list_products_for_reference(db, include_inactive=True, limit=500)
    return [_product_reference_to_dict(product) for product in products]


def _stock_t(lang: str) -> dict[str, str]:
    return STOCK_DOCUMENT_TEXTS.get(lang, STOCK_DOCUMENT_TEXTS["en"])


def _serialize_stock_document_lang_links(request: Request, *, page_name: str, lang: str, **params) -> dict[str, str]:
    shared = {**params}
    return {
        "uk": _url_for(request, page_name, **shared, lang="uk"),
        "en": _url_for(request, page_name, **shared, lang="en"),
        "active": lang,
    }


async def _load_order_stats(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))
    counts = {row[0].value: row[1] for row in result.all()}
    counts["open"] = counts.get("placed", 0) + counts.get("preparing", 0) + counts.get("out_for_delivery", 0)
    return counts


def _template_context(request: Request, **extra) -> dict:
    ui_lang = extra.pop("ui_lang", _resolve_ui_lang(request))
    ui_t = ADMIN_UI_TEXTS.get(ui_lang, ADMIN_UI_TEXTS["en"])
    return {
        "request": request,
        "ui_lang": ui_lang,
        "base_t": ADMIN_BASE_TEXTS.get(ui_lang, ADMIN_BASE_TEXTS["en"]),
        "ui_t": ui_t,
        "order_status_options": [
            (order_status.value, order_status_label_for_lang(order_status, ui_lang))
            for order_status in OrderStatus
        ],
        "order_queue_filter_options": _localized_option_pairs(ORDER_QUEUE_FILTER_LABELS, ui_lang),
        "order_date_filter_options": _localized_option_pairs(ORDER_DATE_FILTER_LABELS, ui_lang),
        "product_category_filter_options": _localized_option_pairs(PRODUCT_CATEGORY_FILTER_LABELS, ui_lang),
        "order_cancellation_reason_options": ORDER_CANCELLATION_REASON_OPTIONS_BY_LANG.get(
            ui_lang,
            ORDER_CANCELLATION_REASON_OPTIONS_BY_LANG["en"],
        ),
        "sales_analytics_period_options": _sales_period_option_pairs(ui_lang),
        "sales_analytics_sort_options": _sales_sort_option_pairs(ui_lang),
        "format_order_status": lambda value, _lang=ui_lang: order_status_label_for_lang(value, _lang),
        "format_delivery_status": lambda value, _lang=ui_lang: delivery_status_label_for_lang(value, _lang),
        "can_assign_order": can_assign_order,
        "can_cancel_order": can_cancel_order,
        "can_edit_order_items": can_edit_order_items,
        "lang_switch_urls": {
            "uk": f"{request.url_for('admin_set_ui_language', lang='uk')}?{urlencode({'next': _current_relative_url(request)})}",
            "en": f"{request.url_for('admin_set_ui_language', lang='en')}?{urlencode({'next': _current_relative_url(request)})}",
            "active": ui_lang,
        },
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
    category_filter: str,
    page: int,
    selected_product_id: int | None = None,
    create_form_data: dict | None = None,
    edit_form_data: dict | None = None,
    adjust_stock_form_data: dict | None = None,
    create_error: str | None = None,
    edit_error: str | None = None,
    adjust_stock_error: str | None = None,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    ui_lang = _resolve_ui_lang(request)
    parsed_page = _parse_page(page)
    total_products = await product_service.count_products(
        db,
        active_status=active_filter,
        search=search,
        stock_status=stock_filter,
        category_filter=category_filter,
    )
    total_pages = max(1, (total_products + ADMIN_PRODUCTS_PAGE_SIZE - 1) // ADMIN_PRODUCTS_PAGE_SIZE)
    if parsed_page > total_pages:
        parsed_page = total_pages

    products = await product_service.get_all_products(
        db,
        sort_field=SortField.name,
        active_status=active_filter,
        sort_order=SortOrder.asc,
        offset=(parsed_page - 1) * ADMIN_PRODUCTS_PAGE_SIZE,
        limit=ADMIN_PRODUCTS_PAGE_SIZE,
        search=search,
        stock_status=stock_filter,
        category_filter=category_filter,
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
            ui_lang=ui_lang,
            stats=await _load_product_stats(db),
            products=[_product_to_dict(product) for product in products],
            selected_product=selected_product,
            selected_product_batches=selected_product_batches,
            selected_product_id=selected_product_id,
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            category_filter=category_filter,
            page=parsed_page,
            total_pages=total_pages,
            total_products=total_products,
            stock_documents_url=_url_for(request, "admin_stock_documents_page", lang=ui_lang),
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
            adjust_stock_form_data=adjust_stock_form_data
            or {
                "target_available_quantity": selected_product["available_quantity"] if selected_product else "",
                "note": "",
            },
            create_error=create_error,
            edit_error=edit_error,
            adjust_stock_error=adjust_stock_error,
            message=message,
        ),
        status_code=status_code,
    )


async def _render_stock_document_create_page(
    request: Request,
    db: AsyncSession,
    *,
    admin_user: User,
    ui_lang: str,
    form_data: dict | None = None,
    rows: list[dict] | None = None,
    error: str | None = None,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    t = _stock_t(ui_lang)
    data = form_data or await _default_stock_document_form_data(db)
    if not data.get("document_number"):
        data["document_number"] = await product_service.get_next_receipt_document_number(
            db,
            document_date=date.fromisoformat(data["document_date"]),
        )
    return templates.TemplateResponse(
        "stock_document_create.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="stock-documents",
            ui_lang=ui_lang,
            stock_t=t,
            stock_document_form_data=data,
            stock_document_rows=rows or _empty_stock_document_rows(),
            stock_document_error=error,
            product_reference_options=await _load_product_reference_options(db),
            stock_documents_nav_url=_url_for(request, "admin_stock_documents_page", lang=ui_lang),
            stock_document_list_url=_url_for(request, "admin_stock_documents_page", lang=ui_lang),
            stock_document_create_url=_url_for(request, "admin_stock_document_new_page", lang=ui_lang),
            stock_document_create_action_url=_url_for(request, "admin_stock_document_create_action", lang=ui_lang),
            stock_document_next_number_url=_url_for(request, "admin_stock_document_next_number", lang=ui_lang),
            message=message,
        ),
        status_code=status_code,
    )


async def _render_stock_document_list_page(
    request: Request,
    db: AsyncSession,
    *,
    admin_user: User,
    ui_lang: str,
    period: str,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    t = _stock_t(ui_lang)
    days_back_map = {
        "today": 1,
        "7d": 7,
        "30d": 30,
        "all": None,
    }
    return templates.TemplateResponse(
        "stock_document_list.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="stock-documents",
            ui_lang=ui_lang,
            stock_t=t,
            stock_document_period=period,
            stock_document_period_options=_stock_document_period_option_pairs(ui_lang),
            recent_stock_documents=[
                _stock_document_to_dict(document)
                for document in await product_service.list_recent_stock_documents(
                    db,
                    limit=40,
                    days_back=days_back_map.get(period, 1),
                )
            ],
            stock_documents_nav_url=_url_for(request, "admin_stock_documents_page", lang=ui_lang),
            stock_document_create_url=_url_for(request, "admin_stock_document_new_page", lang=ui_lang),
            message=message,
        ),
        status_code=status_code,
    )


async def _render_sales_analytics_page(
    request: Request,
    db: AsyncSession,
    *,
    admin_user: User,
    period: SalesAnalyticsPeriod,
    sort_by: SalesAnalyticsSort,
    limit: int,
):
    analytics = await analytics_service.get_product_sales_analytics(
        db,
        period=period,
        sort_by=sort_by,
        limit=limit,
    )
    analytics_items = [
        {
            "product_id": item.product_id,
            "product_name": item.product_name,
            "product_sku": item.product_sku,
            "unit": item.unit,
            "total_quantity": item.total_quantity,
            "total_revenue": item.total_revenue,
            "order_count": item.order_count,
        }
        for item in analytics.items
    ]
    max_quantity = max((item["total_quantity"] for item in analytics_items), default=Decimal("0"))
    max_revenue = max((item["total_revenue"] for item in analytics_items), default=Decimal("0"))
    bottom_items = list(reversed(analytics_items[-5:])) if analytics_items else []

    return templates.TemplateResponse(
        "sales_analytics.html",
        _template_context(
            request,
            admin_user=admin_user,
            section="sales-analytics",
            analytics_period=period.value,
            analytics_sort=sort_by.value,
            analytics_limit=limit,
            analytics_summary={
                "total_products": analytics.summary.total_products,
                "total_quantity": analytics.summary.total_quantity,
                "total_revenue": analytics.summary.total_revenue,
                "total_orders": analytics.summary.total_orders,
            },
            analytics_items=analytics_items,
            analytics_bottom_items=bottom_items,
            analytics_generated_at=analytics.generated_at,
            analytics_period_start=analytics.period_start,
            analytics_period_end=analytics.period_end,
            analytics_max_quantity=max_quantity,
            analytics_max_revenue=max_revenue,
        ),
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


async def _default_stock_document_form_data(db: AsyncSession, *, document_date: date | None = None) -> dict:
    target_date = document_date or kyiv_today()
    return {
        "document_type": STOCK_DOCUMENT_FORM_TYPE.value,
        "document_number": await product_service.get_next_receipt_document_number(db, document_date=target_date),
        "document_date": target_date.isoformat(),
        "supplier_name": "",
        "supplier_phone": "",
        "supplier_email": "",
        "supplier_notes": "",
        "note": "",
    }


def _empty_stock_document_rows(count: int = 6) -> list[dict]:
    return [
        {
            "product_id": "",
            "sku": "",
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
            "product_id",
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
    product_ids = form.getlist("doc_product_id")
    skus = form.getlist("doc_sku")
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
    for product_id, sku, name, unit, sale_unit_price, purchase_unit_price, quantity_value, batch_code, serial_code, expires_at, note in zip(
        product_ids,
        skus,
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
            "product_id": str(product_id).strip(),
            "sku": str(sku).strip(),
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
    except ValueError:
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


@router.get("/ui-language/{lang}", name="admin_set_ui_language")
async def admin_set_ui_language(request: Request, lang: str, next: str = Query(default="/admin/orders")):
    ui_lang = _parse_ui_lang(lang)
    target = next if next.startswith("/") else str(request.url_for("admin_orders_dashboard"))
    response = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        ADMIN_UI_LANG_COOKIE_NAME,
        ui_lang,
        max_age=60 * 60 * 24 * 365,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )
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
    category_filter: str = Query(default="all"),
    selected_product_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
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
        category_filter=_parse_product_category_filter(category_filter),
        page=_parse_page(page),
        selected_product_id=_parse_optional_int(selected_product_id, field_name="selected product id"),
        message=message or None,
    )


@router.get("/stock-documents", response_class=HTMLResponse, name="admin_stock_documents_page")
async def admin_stock_documents_page(
    request: Request,
    lang: str | None = Query(default=None),
    period: str = Query(default="today"),
    message: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    return await _render_stock_document_list_page(
        request,
        db,
        admin_user=admin_user,
        ui_lang=_resolve_ui_lang(request, lang),
        period=_parse_stock_document_period(period),
        message=message or None,
    )


@router.get("/stock-documents/new", response_class=HTMLResponse, name="admin_stock_document_new_page")
async def admin_stock_document_new_page(
    request: Request,
    lang: str | None = Query(default=None),
    message: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    return await _render_stock_document_create_page(
        request,
        db,
        admin_user=admin_user,
        ui_lang=_resolve_ui_lang(request, lang),
        message=message or None,
    )


@router.get("/stock-documents/next-number", name="admin_stock_document_next_number")
async def admin_stock_document_next_number(
    request: Request,
    document_date: str = Query(...),
    lang: str = Query(default="uk"),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Unauthorized"})

    try:
        target_date = date.fromisoformat(document_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document date") from exc
    document_number = await product_service.get_next_receipt_document_number(db, document_date=target_date)
    return JSONResponse({"document_number": document_number, "lang": _parse_ui_lang(lang)})


@router.get("/stock-documents/{document_id}/export.xlsx", name="admin_stock_document_export")
async def admin_stock_document_export(
    request: Request,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    document = await product_service.get_stock_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse document not found")

    rows: list[list[object]] = [
        ["Document number", document.document_number],
        ["Document date", document.document_date.isoformat()],
        ["Supplier", document.supplier.name if document.supplier is not None else ""],
        ["Created by", document.created_by_user.full_name if document.created_by_user is not None else ""],
        ["Note", document.note or ""],
        [],
        ["Product", "Unit", "Input qty", "Applied delta", "Sell price", "Purchase price", "Batch", "Serial", "Expires", "Note"],
    ]
    for item in document.items:
        rows.append(
            [
                item.product_name,
                item.unit,
                item.quantity_value,
                item.applied_delta,
                item.sale_unit_price,
                item.purchase_unit_price,
                item.batch_code or "",
                item.serial_code or "",
                item.expires_at.isoformat() if item.expires_at is not None else "",
                item.note or "",
            ]
        )

    content = build_xlsx_document(
        sheet_name="Invoice" if document.document_type == StockDocumentType.RECEIPT else "Document",
        rows=rows,
    )
    filename = f"{document.document_number}.xlsx".replace("/", "-").replace("\\", "-")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/analytics/products", response_class=HTMLResponse, name="admin_sales_analytics_page")
async def admin_sales_analytics_page(
    request: Request,
    period: str = Query(default=SalesAnalyticsPeriod.month.value),
    sort_by: str = Query(default=SalesAnalyticsSort.quantity.value),
    limit: int = Query(default=30, ge=5, le=100),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    return await _render_sales_analytics_page(
        request,
        db,
        admin_user=admin_user,
        period=_parse_sales_period(period),
        sort_by=_parse_sales_sort(sort_by),
        limit=limit,
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
    category_filter = _parse_product_category_filter(str(form.get("category_filter", "all")))
    selected_product_id = _parse_optional_int(str(form.get("selected_product_id", "")).strip(), field_name="selected product id")
    page = _parse_page(str(form.get("page", "1")).strip())
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
            category_filter=category_filter,
            page=page,
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
            category_filter=category_filter,
            page=page,
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
    category_filter = _parse_product_category_filter(str(form.get("category_filter", "all")))
    page = _parse_page(str(form.get("page", "1")).strip())
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
            category_filter=category_filter,
            page=page,
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
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            message="Product updated successfully.",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{product_id}/adjust-stock", response_class=HTMLResponse, name="admin_product_adjust_stock_action")
async def admin_product_adjust_stock_action(
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
    category_filter = _parse_product_category_filter(str(form.get("category_filter", "all")))
    page = _parse_page(str(form.get("page", "1")).strip())
    target_available_quantity = str(form.get("target_available_quantity", "")).strip()
    note = str(form.get("note", "")).strip()
    adjust_stock_form_data = {
        "target_available_quantity": target_available_quantity,
        "note": note,
    }

    product = await product_service.get_product_by_id(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    try:
        target_quantity = Decimal(target_available_quantity)
    except InvalidOperation as exc:
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            adjust_stock_form_data=adjust_stock_form_data,
            adjust_stock_error="Could not adjust stock: target quantity must be a valid number.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    current_available = Decimal(str(product.available_quantity or 0))
    delta = target_quantity - current_available

    if delta == 0:
        return RedirectResponse(
            url=_url_for(
                request,
                "admin_products_page",
                search=search,
                active_filter=active_filter.value,
                stock_filter=stock_filter.value,
                category_filter=category_filter,
                page=page,
                selected_product_id=product_id,
                message="Free stock was already at the requested quantity.",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        payload = ProductStockDocumentApply.model_validate(
            {
                "document_type": StockDocumentType.ADJUSTMENT,
                "document_date": kyiv_today().isoformat(),
                "note": note or f"Admin stock correction from Products page for {product.name}.",
                "items": [
                    {
                        "product_id": product.id,
                        "name": product.name,
                        "unit": product.unit,
                        "sale_unit_price": str(product.base_unit_price),
                        "purchase_unit_price": str(product.last_purchase_price) if product.last_purchase_price is not None else None,
                        "quantity_value": str(delta),
                    }
                ],
            }
        )
        await product_service.apply_stock_document(db, payload, actor_user_id=admin_user.id)
    except (HTTPException, ValidationError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            adjust_stock_form_data=adjust_stock_form_data,
            adjust_stock_error=f"Could not adjust stock: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_products_page",
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            message="Free stock updated through an adjustment document.",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{product_id}/delete", response_class=HTMLResponse, name="admin_product_delete_action")
async def admin_product_delete_action(
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
    category_filter = _parse_product_category_filter(str(form.get("category_filter", "all")))
    page = _parse_page(str(form.get("page", "1")).strip())
    delete_reason = str(form.get("delete_reason", "")).strip()

    if not delete_reason:
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            adjust_stock_error="Вкажіть причину видалення товару.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        deleted = await product_service.product_delete_by_id(
            db,
            product_id,
            reason=delete_reason,
            actor_user_id=admin_user.id,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    except HTTPException as exc:
        return await _render_products_page(
            request,
            db,
            admin_user=admin_user,
            search=search,
            active_filter=active_filter,
            stock_filter=stock_filter,
            category_filter=category_filter,
            page=page,
            selected_product_id=product_id,
            adjust_stock_error=f"Не вдалося видалити товар: {exc.detail}",
            status_code=exc.status_code if 400 <= exc.status_code < 500 else status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_products_page",
            search=search,
            active_filter=active_filter.value,
            stock_filter=stock_filter.value,
            category_filter=category_filter,
            page=page,
            message="Товар видалено.",
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/stock-documents", response_class=HTMLResponse, name="admin_stock_document_create_action")
async def admin_stock_document_create_action(
    request: Request,
    lang: str = Query(default="uk"),
    db: AsyncSession = Depends(get_db),
):
    admin_user = await _require_admin_user(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    ui_lang = _parse_ui_lang(lang)
    t = _stock_t(ui_lang)
    form = await request.form()
    stock_document_form_data = {
        "document_type": STOCK_DOCUMENT_FORM_TYPE.value,
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
        return await _render_stock_document_create_page(
            request,
            db,
            admin_user=admin_user,
            ui_lang=ui_lang,
            form_data=stock_document_form_data,
            rows=stock_document_rows,
            error=t["no_rows_error"],
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if incomplete_rows:
        return await _render_stock_document_create_page(
            request,
            db,
            admin_user=admin_user,
            ui_lang=ui_lang,
            form_data=stock_document_form_data,
            rows=stock_document_rows,
            error=t["incomplete_rows_error"],
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        try:
            document_date = date.fromisoformat(stock_document_form_data["document_date"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document date") from exc
        document_number = stock_document_form_data["document_number"] or await product_service.get_next_receipt_document_number(
            db,
            document_date=document_date,
        )
        stock_document_form_data["document_number"] = document_number
        payload = ProductStockDocumentApply.model_validate(
            {
                **stock_document_form_data,
                "document_type": STOCK_DOCUMENT_FORM_TYPE,
                "document_date": document_date,
                "items": payload_rows,
            }
        )
        result = await product_service.apply_stock_document(db, payload, actor_user_id=admin_user.id)
    except (HTTPException, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _render_stock_document_create_page(
            request,
            db,
            admin_user=admin_user,
            ui_lang=ui_lang,
            form_data=stock_document_form_data,
            rows=stock_document_rows,
            error=f"{t['apply_error_prefix']}: {detail}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(
        url=_url_for(
            request,
            "admin_stock_documents_page",
            lang=ui_lang,
            message=t["saved_message"].format(created=result.created_count, updated=result.updated_count),
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
