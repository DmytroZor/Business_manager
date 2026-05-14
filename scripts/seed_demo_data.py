from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import selectinload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import AsyncSessionLocal  # noqa: E402
from core.models import Courier, Order, Product, StockDocument, User  # noqa: E402
from core.time_utils import KYIV_TZ, UTC, kyiv_today  # noqa: E402
from manage.schemas.auth_schema import AdminCourierCreate  # noqa: E402
from manage.schemas.delivery_schema import DeliverySelfAssignCreate, DeliveryStatusUpdate  # noqa: E402
from manage.schemas.order_schema import AdminPhoneOrderCreate, OrderItemCreate  # noqa: E402
from manage.schemas.product_schema import ProductStockDocumentApply  # noqa: E402
from manage.services import delivery_service, order_service, product_service  # noqa: E402
from manage.services.auth_service import create_courier_user_by_admin  # noqa: E402


DEMO_TAG = "DEMO-SEED"
DEMO_SUPPLIER_NAME = "Демо постачальник морепродуктів"


@dataclass(slots=True)
class DemoProduct:
    name: str
    unit: str
    sale_price: Decimal
    purchase_price: Decimal
    quantity: Decimal


DEMO_PRODUCTS: list[DemoProduct] = [
    DemoProduct("Сібас цілий", "кг", Decimal("445.00"), Decimal("325.00"), Decimal("18.000")),
    DemoProduct("Дорадо ціла", "кг", Decimal("435.00"), Decimal("315.00"), Decimal("18.000")),
    DemoProduct("Лосось філе", "кг", Decimal("690.00"), Decimal("520.00"), Decimal("16.000")),
    DemoProduct("Форель ціла", "кг", Decimal("420.00"), Decimal("305.00"), Decimal("18.000")),
    DemoProduct("Скумбрія ціла", "кг", Decimal("235.00"), Decimal("165.00"), Decimal("24.000")),
    DemoProduct("Оселедець філе", "кг", Decimal("210.00"), Decimal("145.00"), Decimal("20.000")),
    DemoProduct("Тунець стейк", "кг", Decimal("790.00"), Decimal("610.00"), Decimal("12.000")),
    DemoProduct("Палтус філе", "кг", Decimal("760.00"), Decimal("580.00"), Decimal("12.000")),
    DemoProduct("Тріска філе", "кг", Decimal("390.00"), Decimal("285.00"), Decimal("18.000")),
    DemoProduct("Хек тушка", "кг", Decimal("230.00"), Decimal("160.00"), Decimal("22.000")),
    DemoProduct("Минтай філе", "кг", Decimal("255.00"), Decimal("178.00"), Decimal("18.000")),
    DemoProduct("Камбала ціла", "кг", Decimal("340.00"), Decimal("250.00"), Decimal("14.000")),
    DemoProduct("Креветка тигрова", "кг", Decimal("880.00"), Decimal("690.00"), Decimal("10.000")),
    DemoProduct("Креветка королівська", "кг", Decimal("930.00"), Decimal("730.00"), Decimal("10.000")),
    DemoProduct("Мідії у мушлях", "кг", Decimal("295.00"), Decimal("205.00"), Decimal("16.000")),
    DemoProduct("Мідії очищені", "кг", Decimal("365.00"), Decimal("258.00"), Decimal("14.000")),
    DemoProduct("Кальмар тушка", "кг", Decimal("390.00"), Decimal("278.00"), Decimal("14.000")),
    DemoProduct("Кальмар кільця", "кг", Decimal("420.00"), Decimal("298.00"), Decimal("14.000")),
    DemoProduct("Восьминіг baby", "кг", Decimal("780.00"), Decimal("590.00"), Decimal("8.000")),
    DemoProduct("Гребінець морський", "кг", Decimal("1280.00"), Decimal("1020.00"), Decimal("6.000")),
    DemoProduct("Устриці Фін де Клер", "шт", Decimal("95.00"), Decimal("68.00"), Decimal("80.000")),
    DemoProduct("Крабове м'ясо", "упак", Decimal("365.00"), Decimal("248.00"), Decimal("18.000")),
    DemoProduct("Краб камчатський клешні", "кг", Decimal("1580.00"), Decimal("1270.00"), Decimal("6.000")),
    DemoProduct("Лангустини сирі", "кг", Decimal("860.00"), Decimal("640.00"), Decimal("8.000")),
    DemoProduct("Раки варені", "кг", Decimal("620.00"), Decimal("450.00"), Decimal("10.000")),
    DemoProduct("Ікра лососева", "банка", Decimal("420.00"), Decimal("310.00"), Decimal("20.000")),
    DemoProduct("Ікра тріски", "банка", Decimal("165.00"), Decimal("118.00"), Decimal("20.000")),
    DemoProduct("Лосось слабосолений", "кг", Decimal("810.00"), Decimal("620.00"), Decimal("8.000")),
    DemoProduct("Форель слабосолена", "кг", Decimal("720.00"), Decimal("545.00"), Decimal("8.000")),
    DemoProduct("Вугор копчений", "кг", Decimal("990.00"), Decimal("780.00"), Decimal("7.000")),
    DemoProduct("Анчоуси філе", "упак", Decimal("125.00"), Decimal("86.00"), Decimal("24.000")),
    DemoProduct("Сардина ціла", "кг", Decimal("210.00"), Decimal("150.00"), Decimal("18.000")),
    DemoProduct("Ставрида ціла", "кг", Decimal("195.00"), Decimal("135.00"), Decimal("18.000")),
    DemoProduct("Кефаль ціла", "кг", Decimal("265.00"), Decimal("190.00"), Decimal("16.000")),
    DemoProduct("Корюшка свіжа", "кг", Decimal("340.00"), Decimal("245.00"), Decimal("12.000")),
    DemoProduct("Барабулька ціла", "кг", Decimal("365.00"), Decimal("258.00"), Decimal("12.000")),
    DemoProduct("Морський окунь філе", "кг", Decimal("540.00"), Decimal("395.00"), Decimal("10.000")),
    DemoProduct("Сом філе", "кг", Decimal("310.00"), Decimal("220.00"), Decimal("14.000")),
    DemoProduct("Щука філе", "кг", Decimal("325.00"), Decimal("230.00"), Decimal("14.000")),
    DemoProduct("Судак філе", "кг", Decimal("445.00"), Decimal("320.00"), Decimal("12.000")),
    DemoProduct("Каракатиця ціла", "кг", Decimal("680.00"), Decimal("510.00"), Decimal("8.000")),
    DemoProduct("Морський коктейль", "упак", Decimal("210.00"), Decimal("150.00"), Decimal("28.000")),
    DemoProduct("Філе дорадо", "кг", Decimal("520.00"), Decimal("380.00"), Decimal("10.000")),
    DemoProduct("Філе сібаса", "кг", Decimal("530.00"), Decimal("388.00"), Decimal("10.000")),
    DemoProduct("Філе скумбрії", "кг", Decimal("280.00"), Decimal("198.00"), Decimal("12.000")),
    DemoProduct("Стейк лосося", "кг", Decimal("740.00"), Decimal("560.00"), Decimal("10.000")),
    DemoProduct("Стейк тунця premium", "кг", Decimal("890.00"), Decimal("690.00"), Decimal("8.000")),
    DemoProduct("Філе палтуса premium", "кг", Decimal("840.00"), Decimal("645.00"), Decimal("8.000")),
    DemoProduct("Філе тріски premium", "кг", Decimal("455.00"), Decimal("328.00"), Decimal("12.000")),
    DemoProduct("Креветка салатна", "упак", Decimal("189.00"), Decimal("132.00"), Decimal("24.000")),
    DemoProduct("Креветка аргентинська", "кг", Decimal("970.00"), Decimal("760.00"), Decimal("8.000")),
    DemoProduct("Мідії half shell", "упак", Decimal("248.00"), Decimal("172.00"), Decimal("20.000")),
    DemoProduct("Філе оселедця в олії", "упак", Decimal("118.00"), Decimal("80.00"), Decimal("24.000")),
    DemoProduct("Філе оселедця класичне", "упак", Decimal("112.00"), Decimal("76.00"), Decimal("24.000")),
    DemoProduct("Копчений лосось нарізка", "упак", Decimal("255.00"), Decimal("182.00"), Decimal("18.000")),
    DemoProduct("Копчена скумбрія", "кг", Decimal("330.00"), Decimal("235.00"), Decimal("10.000")),
    DemoProduct("Філе мінтая", "кг", Decimal("275.00"), Decimal("194.00"), Decimal("14.000")),
    DemoProduct("Філе хека", "кг", Decimal("295.00"), Decimal("210.00"), Decimal("14.000")),
    DemoProduct("Рапани очищені", "кг", Decimal("520.00"), Decimal("375.00"), Decimal("8.000")),
    DemoProduct("Морський язик філе", "кг", Decimal("610.00"), Decimal("450.00"), Decimal("10.000")),
    DemoProduct("Тунець для тартару", "кг", Decimal("990.00"), Decimal("770.00"), Decimal("6.000")),
    DemoProduct("Лосось для суші", "кг", Decimal("760.00"), Decimal("575.00"), Decimal("8.000")),
    DemoProduct("Ікра мойви", "банка", Decimal("118.00"), Decimal("82.00"), Decimal("18.000")),
    DemoProduct("Ікра щуки", "банка", Decimal("310.00"), Decimal("220.00"), Decimal("16.000")),
    DemoProduct("Котлети рибні", "упак", Decimal("168.00"), Decimal("116.00"), Decimal("18.000")),
    DemoProduct("Фарш лососевий", "кг", Decimal("395.00"), Decimal("285.00"), Decimal("10.000")),
    DemoProduct("Крабові палички преміум", "упак", Decimal("105.00"), Decimal("72.00"), Decimal("26.000")),
    DemoProduct("Салат із морепродуктів", "упак", Decimal("198.00"), Decimal("140.00"), Decimal("20.000")),
    DemoProduct("Сушені кальмари", "упак", Decimal("132.00"), Decimal("91.00"), Decimal("18.000")),
    DemoProduct("Стружка тунця", "упак", Decimal("176.00"), Decimal("122.00"), Decimal("18.000")),
]


DEMO_COURIERS = [
    {
        "full_name": "Демо Кур'єр 1",
        "phone_number": "+380680001001",
        "password": "courier123",
        "vehicle_info": "Скутер",
        "email": "demo.courier1@example.com",
    },
    {
        "full_name": "Демо Кур'єр 2",
        "phone_number": "+380680001002",
        "password": "courier123",
        "vehicle_info": "Авто",
        "email": "demo.courier2@example.com",
    },
]


def _status_value(value) -> str:
    return getattr(value, "value", str(value))


def _chunked(values: list[DemoProduct], size: int) -> Iterable[list[DemoProduct]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _build_receipt_row(product: DemoProduct, index: int, *, batch_suffix: str, quantity: Decimal | None = None) -> dict:
    expires_at = kyiv_today() + timedelta(days=90 + index)
    return {
        "name": product.name,
        "unit": product.unit,
        "sale_unit_price": str(product.sale_price),
        "purchase_unit_price": str(product.purchase_price),
        "quantity_value": str(quantity if quantity is not None else product.quantity),
        "batch_code": f"{DEMO_TAG}-{batch_suffix}-{index:02d}",
        "expires_at": expires_at.isoformat(),
        "note": f"Демонстраційна позиція {DEMO_TAG}",
    }


async def _stock_document_exists(db, document_number: str) -> bool:
    result = await db.execute(
        select(StockDocument.id).where(StockDocument.document_number == document_number)
    )
    return result.scalar_one_or_none() is not None


async def _stock_document_note_exists(db, note: str) -> bool:
    result = await db.execute(select(StockDocument.id).where(StockDocument.note == note))
    return result.scalar_one_or_none() is not None


async def _existing_demo_product_names(db) -> set[str]:
    result = await db.execute(
        select(Product.name).where(Product.name.in_([product.name for product in DEMO_PRODUCTS]))
    )
    return set(result.scalars().all())


async def _seed_stock_documents(db) -> dict[str, int]:
    today = kyiv_today()
    document_specs: list[tuple[str, ProductStockDocumentApply]] = []
    existing_names = await _existing_demo_product_names(db)
    missing_products = [product for product in DEMO_PRODUCTS if product.name not in existing_names]

    date_plan = [
        today - timedelta(days=2),
        today - timedelta(days=1),
        today,
        today,
    ]
    for chunk_index, chunk in enumerate(_chunked(missing_products, 18), start=1):
        document_date = date_plan[min(chunk_index - 1, len(date_plan) - 1)]
        document_number = await product_service.get_next_receipt_document_number(db, document_date=document_date)
        document_specs.append(
            (
                document_number,
                ProductStockDocumentApply.model_validate(
                    {
                        "document_type": "receipt",
                        "document_number": document_number,
                        "document_date": document_date,
                        "supplier_name": DEMO_SUPPLIER_NAME,
                        "supplier_phone": "+380441112233",
                        "supplier_email": "demo-supplier@example.com",
                        "supplier_notes": "Демонстраційний прихід для перевірки каталогу та складських сценаріїв.",
                        "note": f"{DEMO_TAG} receipt batch {chunk_index}",
                        "items": [
                            _build_receipt_row(product, product_index, batch_suffix=f"REC{chunk_index:02d}")
                            for product_index, product in enumerate(chunk, start=(chunk_index - 1) * 18 + 1)
                        ],
                    }
                ),
            )
        )

    restock_note = f"{DEMO_TAG} restock batch"
    if not await _stock_document_note_exists(db, restock_note):
        restock_date = today
        restock_number = await product_service.get_next_receipt_document_number(db, document_date=restock_date)
        restock_products = [DEMO_PRODUCTS[index] for index in (0, 2, 6, 11, 18, 24, 33, 40, 54, 66)]
        document_specs.append(
            (
                restock_number,
                ProductStockDocumentApply.model_validate(
                    {
                        "document_type": "receipt",
                        "document_number": restock_number,
                        "document_date": restock_date,
                        "supplier_name": DEMO_SUPPLIER_NAME,
                        "supplier_phone": "+380441112233",
                        "supplier_email": "demo-supplier@example.com",
                        "note": restock_note,
                        "items": [
                            _build_receipt_row(
                                product,
                                index + 1,
                                batch_suffix="RESTOCK",
                                quantity=Decimal("4.000") + Decimal(index % 3),
                            )
                            for index, product in enumerate(restock_products)
                        ],
                    }
                ),
            )
        )

    created_documents = 0
    skipped_documents = 0
    for document_number, payload in document_specs:
        if await _stock_document_exists(db, document_number):
            skipped_documents += 1
            continue
        await product_service.apply_stock_document(db, payload)
        created_documents += 1

    return {"created_documents": created_documents, "skipped_documents": skipped_documents}


async def _ensure_demo_couriers(db) -> list[User]:
    created = []
    for courier_spec in DEMO_COURIERS:
        existing_result = await db.execute(
            select(User)
            .options(selectinload(User.courier_profile))
            .where(User.phone == courier_spec["phone_number"])
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            created.append(existing)
            continue
        payload = AdminCourierCreate.model_validate(courier_spec)
        user = await create_courier_user_by_admin(db, payload)
        created.append(user)
    return created


async def _get_demo_product_pool(db, *, limit: int) -> list[Product]:
    names = [product.name for product in DEMO_PRODUCTS[:limit]]
    result = await db.execute(
        select(Product)
        .where(Product.name.in_(names))
        .order_by(Product.name.asc(), Product.id.asc())
    )
    return result.scalars().all()


def _quantity_for_unit(unit: str, *, order_index: int, is_secondary: bool) -> Decimal:
    normalized = unit.strip().casefold()
    if normalized in {"шт", "pcs", "piece", "упак", "банка"}:
        return Decimal("1.000") if is_secondary else Decimal("2.000")
    base = Decimal("0.350") if is_secondary else Decimal("0.550")
    return base + Decimal(order_index % 3) * Decimal("0.050")


def _build_demo_note(order_index: int) -> str:
    return f"[{DEMO_TAG}-ORDER-{order_index:02d}] Демонстраційне телефонне замовлення #{order_index:02d}"


async def _find_order_by_demo_note(db, note: str) -> Order | None:
    result = await db.execute(select(Order).where(Order.note == note))
    return result.scalar_one_or_none()


def _placed_at_for_index(order_index: int) -> datetime:
    today = kyiv_today()
    if order_index <= 12:
        target_date = today
    elif order_index <= 22:
        target_date = today - timedelta(days=1)
    else:
        target_date = today - timedelta(days=2)

    hour = 9 + ((order_index - 1) % 8)
    minute = 10 if order_index % 2 else 35
    local_value = datetime.combine(target_date, time(hour=hour, minute=minute), tzinfo=KYIV_TZ)
    return local_value.astimezone(UTC)


async def _seed_phone_orders(db, *, product_pool: list[Product], order_count: int) -> list[Order]:
    seeded_orders: list[Order] = []

    for order_index in range(1, order_count + 1):
        note = _build_demo_note(order_index)
        existing = await _find_order_by_demo_note(db, note)
        if existing is not None:
            existing.placed_at = _placed_at_for_index(order_index)
            await db.commit()
            seeded_orders.append(existing)
            continue

        primary_product = product_pool[(order_index - 1) % len(product_pool)]
        secondary_product = product_pool[(order_index * 3 + 7) % len(product_pool)]
        if secondary_product.id == primary_product.id:
            secondary_product = product_pool[(order_index * 5 + 11) % len(product_pool)]

        payload = AdminPhoneOrderCreate(
            customer_full_name=f"Тестовий покупець {order_index:02d}",
            customer_phone_number=f"+3806701{order_index:05d}",
            customer_email=None,
            street=f"Вулиця Морська {((order_index - 1) % 9) + 1}",
            building=str(10 + order_index),
            apartment=str((order_index % 12) + 1),
            address_notes="Доставка на наступний день, попередньо зателефонувати.",
            note=note,
            items=[
                OrderItemCreate(
                    product_id=primary_product.id,
                    quantity=_quantity_for_unit(primary_product.unit, order_index=order_index, is_secondary=False),
                ),
                OrderItemCreate(
                    product_id=secondary_product.id,
                    quantity=_quantity_for_unit(secondary_product.unit, order_index=order_index, is_secondary=True),
                ),
            ],
        )
        order = await order_service.create_phone_order_by_admin(db, payload)
        stored_order = await db.get(Order, order.id)
        stored_order.placed_at = _placed_at_for_index(order_index)
        await db.commit()
        seeded_orders.append(stored_order)

    return seeded_orders


async def _apply_demo_courier_flow(db, *, couriers: list[User], seeded_orders: list[Order]) -> None:
    if len(couriers) < 2:
        return

    courier_a = couriers[0]
    courier_b = couriers[1]
    demo_map = {order.note: order for order in seeded_orders}

    tag_1 = _build_demo_note(1)
    tag_2 = _build_demo_note(2)
    tag_3 = _build_demo_note(3)

    if tag_1 in demo_map:
        order = await order_service.get_order_for_admin(db, demo_map[tag_1].id)
        if _status_value(order.status) in {"placed", "preparing"}:
            delivery = await delivery_service.self_assign_delivery(db, order.id, courier_a.id, DeliverySelfAssignCreate())
            if _status_value(delivery.status) in {"assigned", "pending"}:
                delivery = await delivery_service.pick_up_delivery(db, delivery.id, courier_a.courier_profile.id)
                await delivery_service.complete_delivery(db, delivery.id, courier_a.courier_profile.id)

    if tag_2 in demo_map:
        order = await order_service.get_order_for_admin(db, demo_map[tag_2].id)
        if _status_value(order.status) in {"placed", "preparing"}:
            delivery = await delivery_service.self_assign_delivery(db, order.id, courier_a.id, DeliverySelfAssignCreate())
            if _status_value(delivery.status) in {"assigned", "pending"}:
                delivery = await delivery_service.pick_up_delivery(db, delivery.id, courier_a.courier_profile.id)
                await delivery_service.fail_delivery(
                    db,
                    delivery.id,
                    courier_a.courier_profile.id,
                    DeliveryStatusUpdate(failed_reason="Клієнт попросив перенести доставку."),
                )

    if tag_3 in demo_map:
        order = await order_service.get_order_for_admin(db, demo_map[tag_3].id)
        if _status_value(order.status) in {"placed", "preparing"}:
            await delivery_service.self_assign_delivery(db, order.id, courier_b.id, DeliverySelfAssignCreate())


async def seed_demo_data(*, product_count: int = 70, order_count: int = 30) -> None:
    async with AsyncSessionLocal() as db:
        print("== Demo seed started ==")

        stock_result = await _seed_stock_documents(db)
        print(
            f"Invoices: created {stock_result['created_documents']}, "
            f"skipped existing {stock_result['skipped_documents']}"
        )

        couriers = await _ensure_demo_couriers(db)
        print(f"Couriers available: {len(couriers)}")

        product_pool = await _get_demo_product_pool(db, limit=product_count)
        if len(product_pool) < product_count:
            raise RuntimeError(
                f"Expected at least {product_count} demo products after receipts, but found only {len(product_pool)}."
            )
        print(f"Products available for showcase: {len(product_pool)}")

        seeded_orders = await _seed_phone_orders(db, product_pool=product_pool, order_count=order_count)
        print(f"Phone orders ensured: {len(seeded_orders)}")

        await _apply_demo_courier_flow(db, couriers=couriers, seeded_orders=seeded_orders)
        print("Courier scenarios prepared for today.")

        print("\nCourier login credentials:")
        for courier_spec in DEMO_COURIERS:
            print(
                f"- {courier_spec['full_name']}: {courier_spec['phone_number']} / {courier_spec['password']}"
            )

        print("\nDone. Open the admin panel and Telegram clients to inspect the seeded dataset.")


def main() -> None:
    asyncio.run(seed_demo_data())


if __name__ == "__main__":
    main()
