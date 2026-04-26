from decimal import Decimal

import pytest

from core.models import Address, Customer, OrderStatus, Product, User, UserRole
from manage.schemas.order_schema import OrderCreate, OrderItemCreate
from manage.schemas.review_schema import CreateReview
from manage.services.order_service import create_order
from manage.services.review_service import create_review, get_my_reviews


async def _seed_customer_order(db_session, *, suffix: str) -> tuple[User, Customer, Address, Product, object]:
    user = User(
        full_name=f"Review User {suffix}",
        email=f"review.{suffix}@example.com",
        phone=f"+38066111{suffix}",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()

    customer = Customer(user_id=user.id)
    db_session.add(customer)
    await db_session.flush()

    address = Address(customer_id=customer.id, street="Test", building="1", apartment=None, notes=None)
    product = Product(
        name=f"Review Fish {suffix}",
        sku=f"RIBA-REVIEW-{suffix}",
        description="Fresh fish",
        base_unit_price=Decimal("55.00"),
        unit="kg",
        is_active=True,
    )
    db_session.add_all([address, product])
    await db_session.commit()

    order = await create_order(
        db_session,
        user_id=user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("1.000"))],
        ),
    )
    return user, customer, address, product, order


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_review_allows_cancelled_order(db_session):
    user, customer, _, _, order = await _seed_customer_order(db_session, suffix="8801")

    order.status = OrderStatus.CANCELLED
    await db_session.commit()
    await db_session.refresh(order)

    review = await create_review(
        db_session,
        customer.id,
        order.id,
        CreateReview(rating=4, comment="Замовлення не приїхало, але сервіс був ввічливий"),
    )

    assert review.order_id == order.id
    assert review.customer_id == customer.id
    assert review.rating == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_my_reviews_returns_only_current_customer_reviews(db_session):
    user_a, customer_a, _, _, order_a = await _seed_customer_order(db_session, suffix="8802")
    user_b, customer_b, _, _, order_b = await _seed_customer_order(db_session, suffix="8803")

    order_a.status = OrderStatus.DELIVERED
    order_b.status = OrderStatus.CANCELLED
    await db_session.commit()

    await create_review(
        db_session,
        customer_a.id,
        order_a.id,
        CreateReview(rating=5, comment="Все чудово"),
    )
    await create_review(
        db_session,
        customer_b.id,
        order_b.id,
        CreateReview(rating=3, comment="Замовлення скасували"),
    )

    my_reviews = await get_my_reviews(db_session, customer_a.id)

    assert len(my_reviews) == 1
    assert my_reviews[0].customer_id == customer_a.id
    assert my_reviews[0].order_id == order_a.id
