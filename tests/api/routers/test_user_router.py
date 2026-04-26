from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import get_db
from core.models import UserRole
from routers import user_router
from routers.user_router import get_current_user
from tests.conftest import create_test_client


async def _fake_db():
    yield object()


def test_link_telegram_account_returns_user(monkeypatch):
    linked_user = SimpleNamespace(
        id=1,
        full_name="Courier Test",
        phone="+380501234567",
        email="courier@example.com",
        telegram_id="123456789",
        role=UserRole.COURIER,
    )
    monkeypatch.setattr(
        user_router,
        "link_telegram_account",
        AsyncMock(return_value=linked_user),
    )
    client = create_test_client(
        user_router.router,
        dependency_overrides={
            get_db: _fake_db,
            get_current_user: lambda: SimpleNamespace(id=1),
        },
    )

    response = client.post("/users/me/telegram-link", json={"telegram_id": "123456789"})

    assert response.status_code == 200
    body = response.json()
    assert body["telegram_id"] == "123456789"
    assert body["role"] == "courier"


def test_admin_list_couriers_returns_profiles(monkeypatch):
    async def _fake_execute(*args, **kwargs):
        class _Result:
            def scalars(self):
                class _Scalars:
                    def all(self_nonlocal):
                        return [
                            SimpleNamespace(
                                id=7,
                                full_name="Courier One",
                                phone="+380501112233",
                                email="courier1@example.com",
                                telegram_id="12345",
                                role=UserRole.COURIER,
                                is_active=True,
                                courier_profile=SimpleNamespace(id=3, vehicle_info="bike"),
                            )
                        ]

                return _Scalars()

        return _Result()

    fake_db = SimpleNamespace(execute=AsyncMock(side_effect=_fake_execute))

    async def _fake_db_admin():
        yield fake_db

    client = create_test_client(
        user_router.router,
        dependency_overrides={
            get_db: _fake_db_admin,
            get_current_user: lambda: SimpleNamespace(id=99, role=UserRole.ADMIN),
        },
    )

    response = client.get("/users/admin/couriers")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["profile_id"] == 3
    assert body[0]["role"] == "courier"
