from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SalesAnalyticsPeriod(str, Enum):
    today = "today"
    week = "week"
    month = "month"
    half_year = "half_year"
    year = "year"
    all_time = "all"


class SalesAnalyticsSort(str, Enum):
    quantity = "quantity"
    revenue = "revenue"
    order_count = "order_count"


class ProductSalesAnalyticsRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int | None = Field(None, description="Current product id when still present in catalog.")
    product_name: str = Field(..., description="Snapshot product name from order items.")
    product_sku: str | None = Field(None, description="Snapshot SKU from order items.")
    unit: str = Field(..., description="Product unit.")
    total_quantity: Decimal = Field(..., description="Total sold quantity in the selected period.")
    total_revenue: Decimal = Field(..., description="Total revenue based on item subtotal snapshots.")
    order_count: int = Field(..., description="How many orders included this product.")


class ProductSalesAnalyticsSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_products: int = Field(..., description="How many unique products were sold.")
    total_quantity: Decimal = Field(..., description="Total sold quantity for the selected period.")
    total_revenue: Decimal = Field(..., description="Total revenue for the selected period.")
    total_orders: int = Field(..., description="How many non-cancelled orders were included.")


class ProductSalesAnalyticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period: SalesAnalyticsPeriod = Field(..., description="Selected analytics period.")
    sort_by: SalesAnalyticsSort = Field(..., description="Current sort field.")
    generated_at: datetime = Field(..., description="UTC generation timestamp.")
    period_start: datetime | None = Field(None, description="UTC lower bound used for filtering.")
    period_end: datetime | None = Field(None, description="UTC upper bound used for filtering.")
    summary: ProductSalesAnalyticsSummaryOut = Field(..., description="High-level sales summary.")
    items: list[ProductSalesAnalyticsRowOut] = Field(..., description="Per-product analytics rows.")
