from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import Order, Product, StockDocument
from manage.schemas.product_schema import ActiveStatus, SortField, SortOrder, StockStatus
from manage.services import analytics_service, order_service, product_service
from manage.services.analytics_service import SalesAnalyticsPeriod, SalesAnalyticsSort


def _read_database_url_from_project_env() -> str | None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return value.strip()
    return None


@pytest.fixture(scope="session")
def live_database_url() -> str:
    url = _read_database_url_from_project_env()
    if not url:
        pytest.skip("DATABASE_URL is not configured in the project .env file. Skipping live database smoke tests.")
    return url


@pytest.fixture(scope="session")
async def live_engine(live_database_url: str):
    engine = create_async_engine(
        live_database_url,
        echo=False,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def live_session_maker(live_engine):
    return async_sessionmaker(
        bind=live_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def live_db_session(live_session_maker):
    async with live_session_maker() as session:
        yield session
        await session.rollback()


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_live_database_read_only_smoke(live_db_session):
    product_count = await live_db_session.scalar(select(func.count(Product.id)))
    order_count = await live_db_session.scalar(select(func.count(Order.id)))
    stock_document_count = await live_db_session.scalar(select(func.count(StockDocument.id)))

    products = await product_service.get_all_products(
        live_db_session,
        sort_field=SortField.name,
        active_status=ActiveStatus.all_products,
        sort_order=SortOrder.asc,
        offset=0,
        limit=10,
        stock_status=StockStatus.all_products,
    )
    assert len(products) <= 10
    assert (product_count or 0) >= 0
    assert (order_count or 0) >= 0
    assert (stock_document_count or 0) >= 0

    if products:
        first_product = products[0]
        assert first_product.name
        batches = await product_service.get_product_batches(live_db_session, first_product.id, limit=5)
        assert len(batches) <= 5

    recent_documents = await product_service.list_recent_stock_documents(live_db_session, limit=5)
    assert len(recent_documents) <= 5

    admin_order_count = await order_service.count_orders_for_admin(live_db_session)
    admin_orders = await order_service.get_orders_for_admin(live_db_session, limit=5)
    assert admin_order_count >= 0
    assert len(admin_orders) <= 5

    analytics = await analytics_service.get_product_sales_analytics(
        live_db_session,
        period=SalesAnalyticsPeriod.month,
        sort_by=SalesAnalyticsSort.quantity,
        limit=10,
    )
    assert analytics.summary.total_products >= 0
    assert len(analytics.items) <= 10
