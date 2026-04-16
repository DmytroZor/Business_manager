import os

import pytest
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import Base


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured. Skipping integration tests.")
    return url


@pytest.fixture(scope="session")
async def integration_engine(test_database_url: str):
    engine = create_async_engine(
        test_database_url,
        echo=False,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_schema(integration_engine):
    async with integration_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def integration_session_maker(integration_engine):
    return async_sessionmaker(bind=integration_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session(integration_session_maker):
    session_factory = integration_session_maker
    async with session_factory() as session:
        yield session
