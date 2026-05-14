from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Order, OrderItem, OrderStatus
from core.time_utils import KYIV_TZ, UTC
from manage.schemas.analytics_schema import SalesAnalyticsPeriod, SalesAnalyticsSort


INCLUDED_ORDER_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.PAID,
    OrderStatus.PREPARING,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
)


@dataclass(slots=True)
class ProductSalesAnalyticsRow:
    product_id: int | None
    product_name: str
    product_sku: str | None
    unit: str
    total_quantity: Decimal
    total_revenue: Decimal
    order_count: int


@dataclass(slots=True)
class ProductSalesAnalyticsSummary:
    total_products: int
    total_quantity: Decimal
    total_revenue: Decimal
    total_orders: int


@dataclass(slots=True)
class ProductSalesAnalyticsResult:
    period: SalesAnalyticsPeriod
    sort_by: SalesAnalyticsSort
    generated_at: datetime
    period_start: datetime | None
    period_end: datetime | None
    summary: ProductSalesAnalyticsSummary
    items: list[ProductSalesAnalyticsRow]


def _period_bounds(period: SalesAnalyticsPeriod) -> tuple[datetime | None, datetime | None]:
    now_local = datetime.now(KYIV_TZ)
    today = now_local.date()

    if period == SalesAnalyticsPeriod.all_time:
        return None, None

    if period == SalesAnalyticsPeriod.today:
        start_date = today
    elif period == SalesAnalyticsPeriod.week:
        start_date = today - timedelta(days=6)
    elif period == SalesAnalyticsPeriod.month:
        start_date = today - timedelta(days=29)
    elif period == SalesAnalyticsPeriod.half_year:
        start_date = today - timedelta(days=179)
    else:
        start_date = today - timedelta(days=364)

    start_local = datetime.combine(start_date, time.min, tzinfo=KYIV_TZ)
    end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=KYIV_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


async def get_product_sales_analytics(
    db: AsyncSession,
    *,
    period: SalesAnalyticsPeriod = SalesAnalyticsPeriod.month,
    sort_by: SalesAnalyticsSort = SalesAnalyticsSort.quantity,
    limit: int = 100,
) -> ProductSalesAnalyticsResult:
    period_start, period_end = _period_bounds(period)

    base_filters = [Order.status.in_(INCLUDED_ORDER_STATUSES)]
    if period_start is not None:
        base_filters.append(Order.placed_at >= period_start)
    if period_end is not None:
        base_filters.append(Order.placed_at < period_end)

    rows_stmt = (
        select(
            func.max(OrderItem.product_id).label("product_id"),
            OrderItem.product_name.label("product_name"),
            OrderItem.product_sku.label("product_sku"),
            OrderItem.unit.label("unit"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("total_quantity"),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label("total_revenue"),
            func.count(distinct(Order.id)).label("order_count"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*base_filters)
        .group_by(OrderItem.product_name, OrderItem.product_sku, OrderItem.unit)
    )

    if sort_by == SalesAnalyticsSort.revenue:
        rows_stmt = rows_stmt.order_by(
            func.coalesce(func.sum(OrderItem.subtotal), 0).desc(),
            func.coalesce(func.sum(OrderItem.quantity), 0).desc(),
            OrderItem.product_name.asc(),
        )
    elif sort_by == SalesAnalyticsSort.order_count:
        rows_stmt = rows_stmt.order_by(
            func.count(distinct(Order.id)).desc(),
            func.coalesce(func.sum(OrderItem.quantity), 0).desc(),
            OrderItem.product_name.asc(),
        )
    else:
        rows_stmt = rows_stmt.order_by(
            func.coalesce(func.sum(OrderItem.quantity), 0).desc(),
            func.coalesce(func.sum(OrderItem.subtotal), 0).desc(),
            OrderItem.product_name.asc(),
        )

    rows_stmt = rows_stmt.limit(limit)
    rows_result = await db.execute(rows_stmt)

    items = [
        ProductSalesAnalyticsRow(
            product_id=row.product_id,
            product_name=row.product_name,
            product_sku=row.product_sku,
            unit=row.unit,
            total_quantity=Decimal(str(row.total_quantity or 0)),
            total_revenue=Decimal(str(row.total_revenue or 0)),
            order_count=int(row.order_count or 0),
        )
        for row in rows_result
    ]

    unique_products_stmt = (
        select(
            OrderItem.product_name,
            OrderItem.product_sku,
            OrderItem.unit,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*base_filters)
        .group_by(OrderItem.product_name, OrderItem.product_sku, OrderItem.unit)
        .subquery()
    )

    totals_stmt = (
        select(
            func.count(distinct(Order.id)).label("total_orders"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("total_quantity"),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label("total_revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*base_filters)
    )
    totals = (await db.execute(totals_stmt)).one()
    total_products = await db.scalar(select(func.count()).select_from(unique_products_stmt))

    summary = ProductSalesAnalyticsSummary(
        total_products=int(total_products or 0),
        total_quantity=Decimal(str(totals.total_quantity or 0)),
        total_revenue=Decimal(str(totals.total_revenue or 0)),
        total_orders=int(totals.total_orders or 0),
    )

    return ProductSalesAnalyticsResult(
        period=period,
        sort_by=sort_by,
        generated_at=datetime.now(UTC),
        period_start=period_start,
        period_end=period_end,
        summary=summary,
        items=items,
    )
