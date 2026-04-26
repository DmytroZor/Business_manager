from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.db import get_db
from core.models import Order, OrderStatus, Product, User
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
                "telegram_id": "111222333",
            }
            register_response = await client.post("/users/register", json=register_payload)
            assert register_response.status_code == 201
            assert register_response.json()["user"]["telegram_id"] == "111222333"

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
async def test_login_and_link_existing_courier_and_self_assign_delivery(integration_session_maker):
    async def override_get_db():
        async with integration_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            customer_register = await client.post(
                "/users/register",
                json={
                    "full_name": "Courier Flow Customer",
                    "email": "courier.flow.customer@example.com",
                    "password": "1234567",
                    "phone_number": "+380731119999",
                    "user_role": "customer",
                },
            )
            assert customer_register.status_code == 201

            courier_register = await client.post(
                "/users/register",
                json={
                    "full_name": "Courier Flow User",
                    "email": "courier.flow@example.com",
                    "password": "1234567",
                    "phone_number": "+380671119999",
                    "user_role": "courier",
                },
            )
            assert courier_register.status_code == 201

            customer_login = await client.post(
                "/users/login",
                data={"username": "courier.flow.customer@example.com", "password": "1234567"},
            )
            customer_token = customer_login.json()["access_token"]
            customer_headers = {"Authorization": f"Bearer {customer_token}"}

            address_response = await client.post(
                "/address/",
                json={"street": "Courier", "building": "99", "apartment": None, "notes": None},
                headers=customer_headers,
            )
            assert address_response.status_code == 201

            async with integration_session_maker() as seed_session:
                product = Product(
                    name="Hake",
                    sku="RIBA-INTEGRATION-03",
                    description="Fresh hake",
                    base_unit_price=Decimal("70.00"),
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
                    "delivery_address_id": address_response.json()["id"],
                    "items": [{"product_id": product_id, "quantity": "1.000"}],
                },
                headers=customer_headers,
            )
            assert order_response.status_code == 201
            order_id = order_response.json()["id"]

            courier_login = await client.post(
                "/users/login",
                data={"username": "courier.flow@example.com", "password": "1234567"},
            )
            assert courier_login.status_code == 200
            courier_token = courier_login.json()["access_token"]
            courier_headers = {"Authorization": f"Bearer {courier_token}"}

            telegram_link = await client.post(
                "/users/me/telegram-link",
                json={"telegram_id": "courier-telegram-123"},
                headers=courier_headers,
            )
            assert telegram_link.status_code == 200
            assert telegram_link.json()["telegram_id"] == "courier-telegram-123"
            assert telegram_link.json()["role"] == "courier"

            available_orders = await client.get("/deliveries/available-orders", headers=courier_headers)
            assert available_orders.status_code == 200
            assert available_orders.json()[0]["id"] == order_id

            assign_response = await client.post(
                f"/deliveries/orders/{order_id}/self-assign",
                json={},
                headers=courier_headers,
            )
            assert assign_response.status_code == 201, assign_response.text
            assert assign_response.json()["order_id"] == order_id

            available_after = await client.get("/deliveries/available-orders", headers=courier_headers)
            assert available_after.status_code == 200
            assert available_after.json() == []
    finally:
        app.dependency_overrides.clear()


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_customer_can_leave_review_for_cancelled_order(integration_session_maker):
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
                    "full_name": "Cancelled Review User",
                    "email": "cancelled.review@example.com",
                    "password": "1234567",
                    "phone_number": "+380631117777",
                    "user_role": "customer",
                },
            )
            assert register_response.status_code == 201

            login_response = await client.post(
                "/users/login",
                data={"username": "cancelled.review@example.com", "password": "1234567"},
            )
            assert login_response.status_code == 200
            token = login_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            address_response = await client.post(
                "/address/",
                json={"street": "Review", "building": "7", "apartment": None, "notes": None},
                headers=headers,
            )
            assert address_response.status_code == 201

            async with integration_session_maker() as seed_session:
                product = Product(
                    name="Sea bass",
                    sku="RIBA-INTEGRATION-REVIEW-01",
                    description="Fresh bass",
                    base_unit_price=Decimal("95.00"),
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
                    "delivery_address_id": address_response.json()["id"],
                    "items": [{"product_id": product_id, "quantity": "1.000"}],
                },
                headers=headers,
            )
            assert order_response.status_code == 201
            order_id = order_response.json()["id"]

            async with integration_session_maker() as session:
                order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
                order.status = OrderStatus.CANCELLED
                await session.commit()

            review_response = await client.post(
                f"/reviews/orders/{order_id}",
                json={"rating": 4, "comment": "Замовлення скасували, але підтримка спрацювала добре"},
                headers=headers,
            )
            assert review_response.status_code == 201, review_response.text

            my_reviews_response = await client.get("/reviews/my", headers=headers)
            assert my_reviews_response.status_code == 200
            assert len(my_reviews_response.json()) == 1
            assert my_reviews_response.json()[0]["order_id"] == order_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_can_create_phone_order_and_cancel_it(integration_session_maker):
    async def override_get_db():
        async with integration_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            admin_register = await client.post(
                "/users/register",
                json={
                    "full_name": "Admin Flow User",
                    "email": "admin.flow@example.com",
                    "password": "1234567",
                    "phone_number": "+380671110001",
                    "user_role": "admin",
                },
            )
            assert admin_register.status_code == 201

            admin_login = await client.post(
                "/users/login",
                data={"username": "admin.flow@example.com", "password": "1234567"},
            )
            assert admin_login.status_code == 200
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

            async with integration_session_maker() as seed_session:
                product = Product(
                    name="Pike perch",
                    sku="RIBA-INTEGRATION-ADMIN-01",
                    description="Fresh fish",
                    base_unit_price=Decimal("110.00"),
                    unit="kg",
                    is_active=True,
                )
                seed_session.add(product)
                await seed_session.commit()
                await seed_session.refresh(product)
                product_id = product.id

            create_response = await client.post(
                "/orders/admin/phone-order",
                json={
                    "customer_full_name": "Phone Order Customer",
                    "customer_phone_number": "+380931112233",
                    "customer_email": "phone.order@example.com",
                    "street": "Saksahanskoho",
                    "building": "15",
                    "apartment": "22",
                    "address_notes": "Ring the bell",
                    "note": "Client called by phone",
                    "items": [{"product_id": product_id, "quantity": "1.500"}],
                },
                headers=admin_headers,
            )
            assert create_response.status_code == 201, create_response.text
            created_body = create_response.json()
            assert created_body["customer"]["phone"] == "+380931112233"
            assert created_body["delivery_address"]["street"] == "Saksahanskoho"
            assert created_body["status"] == "placed"
            order_id = created_body["id"]

            orders_response = await client.get("/orders/admin/orders", headers=admin_headers)
            assert orders_response.status_code == 200
            assert len(orders_response.json()) == 1

            cancel_response = await client.patch(
                f"/orders/admin/orders/{order_id}/cancel",
                json={"reason": "Client changed mind"},
                headers=admin_headers,
            )
            assert cancel_response.status_code == 200, cancel_response.text
            assert cancel_response.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()
