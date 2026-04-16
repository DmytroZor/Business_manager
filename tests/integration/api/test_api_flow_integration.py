from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.db import get_db
from core.models import Order, Product, User
from main import app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_login_create_address_and_order(integration_session_maker):
    async def override_get_db():
        async with integration_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            register_payload = {
                "full_name": "Integration Flow User",
                "email": "flow.user@example.com",
                "password": "1234567",
                "phone_number": "+380501112233",
                "user_role": "customer",
            }
            register_response = await client.post("/users/register", json=register_payload)
            assert register_response.status_code == 201

            login_response = await client.post(
                "/users/login",
                data={"username": "flow.user@example.com", "password": "1234567"},
            )
            assert login_response.status_code == 200
            token = login_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            address_response = await client.post(
                "/address/",
                json={
                    "street": "Shevchenko",
                    "building": "10/A",
                    "apartment": "12",
                    "notes": "Call first",
                },
                headers=headers,
            )
            assert address_response.status_code == 201
            address_id = address_response.json()["id"]

            async with integration_session_maker() as seed_session:
                product = Product(
                    name="Trout",
                    sku="RIBA-INTEGRATION-01",
                    description="Fresh trout",
                    base_unit_price=Decimal("80.00"),
                    unit="kg",
                    is_active=True,
                )
                seed_session.add(product)
                await seed_session.commit()
                await seed_session.refresh(product)
                product_id = product.id

            order_response = await client.post(
                "/orders/",
                json={
                    "delivery_address_id": address_id,
                    "note": "Deliver quickly",
                    "items": [{"product_id": product_id, "quantity": "1.250"}],
                },
                headers=headers,
            )
            assert order_response.status_code == 201, order_response.text
            order_body = order_response.json()
            assert order_body["total_amount"] == "100.00"
            assert len(order_body["items"]) == 1

            orders_response = await client.get("/orders/", headers=headers)
            assert orders_response.status_code == 200
            assert len(orders_response.json()) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_rejects_wrong_password(integration_session_maker):
    async def override_get_db():
        async with integration_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            register_response = await client.post(
                "/users/register",
                json={
                    "full_name": "Wrong Password User",
                    "email": "wrong.password@example.com",
                    "password": "1234567",
                    "phone_number": "+380631112233",
                    "user_role": "customer",
                },
            )
            assert register_response.status_code == 201

            login_response = await client.post(
                "/users/login",
                data={"username": "wrong.password@example.com", "password": "bad-password"},
            )
            assert login_response.status_code == 401
    finally:
        app.dependency_overrides.clear()

    async with integration_session_maker() as verify_session:
        user = (
            await verify_session.execute(select(User).where(User.email == "wrong.password@example.com"))
        ).scalar_one_or_none()
        assert user is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_creation_rejects_foreign_address(integration_session_maker):
    async def override_get_db():
        async with integration_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # User A
            await client.post(
                "/users/register",
                json={
                    "full_name": "User A",
                    "email": "user.a@example.com",
                    "password": "1234567",
                    "phone_number": "+380731112233",
                    "user_role": "customer",
                },
            )
            login_a = await client.post("/users/login", data={"username": "user.a@example.com", "password": "1234567"})
            token_a = login_a.json()["access_token"]
            headers_a = {"Authorization": f"Bearer {token_a}"}
            address_a = await client.post(
                "/address/",
                json={"street": "Central", "building": "5", "apartment": "1", "notes": None},
                headers=headers_a,
            )
            assert address_a.status_code == 201
            foreign_address_id = address_a.json()["id"]

            # User B
            await client.post(
                "/users/register",
                json={
                    "full_name": "User B",
                    "email": "user.b@example.com",
                    "password": "1234567",
                    "phone_number": "+380741112233",
                    "user_role": "customer",
                },
            )
            login_b = await client.post("/users/login", data={"username": "user.b@example.com", "password": "1234567"})
            token_b = login_b.json()["access_token"]
            headers_b = {"Authorization": f"Bearer {token_b}"}

            async with integration_session_maker() as seed_session:
                product = Product(
                    name="Salmon",
                    sku="RIBA-INTEGRATION-02",
                    description="Fresh salmon",
                    base_unit_price=Decimal("120.00"),
                    unit="kg",
                    is_active=True,
                )
                seed_session.add(product)
                await seed_session.commit()
                await seed_session.refresh(product)
                product_id = product.id

            denied_order = await client.post(
                "/orders/",
                json={
                    "delivery_address_id": foreign_address_id,
                    "items": [{"product_id": product_id, "quantity": "1.000"}],
                },
                headers=headers_b,
            )
            assert denied_order.status_code == 400, denied_order.text
    finally:
        app.dependency_overrides.clear()

    async with integration_session_maker() as verify_session:
        orders = (await verify_session.execute(select(Order))).scalars().all()
        assert len(orders) == 0
