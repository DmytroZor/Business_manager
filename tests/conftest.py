import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Ensure required settings exist before importing app modules in tests.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION", "3600")
os.environ.setdefault("JWT_REFRESH_EXPIRATION", "604800")


def create_test_client(router, dependency_overrides=None):
    app = FastAPI()
    app.include_router(router)
    for dep, override in (dependency_overrides or {}).items():
        app.dependency_overrides[dep] = override
    return TestClient(app)


@pytest.fixture
def fake_user():
    return SimpleNamespace(id=1, role="customer")
