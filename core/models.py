"""
SQLAlchemy models for a Fish Delivery application (single-city business)

This file contains:
- Declarative SQLAlchemy models (classes) representing the database tables.
- Clear comments for each table explaining its purpose, foreign keys and relationships.

Business assumptions baked into the schema:
- Delivery operates in a single city (no cities table required).
- Orders are placed by Customers, fulfilled by Couriers, and consist of multiple OrderItems.
- Delivery is modeled as a separate Delivery entity to allow multiple delivery attempts, statuses and assignment to a courier.
- Payments are recorded separately from orders to allow multiple payment attempts/refunds.

You can iterate on these models (add fields, indexes, constraints) depending on performance and product needs.

NOTE: This file is intentionally verbose in comments to explain the logic of tables and relationships.
"""

from datetime import datetime
import enum
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text,
    Numeric, Enum as SAEnum, Float, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# --- Enums ---
class OrderStatus(enum.Enum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    PREPARING = "preparing"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class DeliveryStatus(enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    FAILED = "failed"


# -----------------
# Core domain tables
# -----------------

class Customer(Base):
    """Stores the customer data.

    - We separate Customer from Address so a customer can have multiple delivery addresses
      (home, work, etc.) even if the service is in one city.
    - phone is used for contact and unique constraint to avoid exact duplicates.
    """
    __tablename__ = "customer"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=True, index=True)
    phone = Column(String(30), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationships
    addresses = relationship("Address", back_populates="customer", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="customer")


class Address(Base):
    """Delivery addresses for customers.

    Fields:
    - customer_id: FK to Customer
    - street / building / apartment: textual fields. Could be normalized further but are left simple.
    - lat/lon: optional coordinates to enable routing optimizations.

    Reasoning: Keeping addresses separate allows a customer to save multiple addresses and re-use them.
    """
    __tablename__ = "address"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(50), nullable=True)  # e.g., 'Home', 'Work'
    street = Column(String(255), nullable=False)
    building = Column(String(50), nullable=True)
    apartment = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)  # additional delivery instructions
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationship
    customer = relationship("Customer", back_populates="addresses")
    orders = relationship("Order", back_populates="delivery_address")


class Courier(Base):
    """Delivery worker (courier) who picks up prepared fish orders and delivers them.

    - phone unique so we can contact and identify couriers.
    - is_active indicates whether the courier is currently available to accept assignments.
    """
    __tablename__ = "courier"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(200), nullable=False)
    phone = Column(String(30), nullable=False, unique=True)
    vehicle_info = Column(String(200), nullable=True)  # bike, car, etc.
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationships
    deliveries = relationship("Delivery", back_populates="courier")


class Product(Base):
    """Represents a fish product type available for sale.

    - name: e.g., 'Salmon fillet', 'Trout whole'
    - base_unit_price: standard price per unit (could be per kg or per piece depending on unit)
    - unit: textual description of unit, e.g. 'kg', 'piece'
    - is_active: if the product is discontinued, set False


    """
    __tablename__ = "product"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    base_unit_price = Column(Numeric(10, 2), nullable=False)
    unit = Column(String(20), nullable=False, default="kg")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationships
    order_items = relationship("OrderItem", back_populates="product")



# -------------------------
# Orders, items, and payment
# -------------------------

class Order(Base):
    """Customer order placed on the platform.

    - customer_id: FK to Customer
    - delivery_address_id: FK to Address (where to deliver)
    - status: order lifecycle (placed, paid, preparing, out_for_delivery, etc.)
    - total_amount: denormalized total price snapshot at order creation
    - note: optional notes from the customer

    An order can have multiple OrderItems. The order's totals should be re-calculated when items change.
    """
    __tablename__ = "order"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="SET NULL"), nullable=True, index=True)
    delivery_address_id = Column(Integer, ForeignKey("address.id", ondelete="SET NULL"), nullable=True)
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.PLACED)
    placed_at = Column(DateTime, default=datetime.now, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    note = Column(Text, nullable=True)
    # relationships
    customer = relationship("Customer", back_populates="orders")
    delivery_address = relationship("Address", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="order")
    deliveries = relationship("Delivery", back_populates="order")

    # Index to speed queries for recent orders
    __table_args__ = (
        Index("ix_order_customer_status", "customer_id", "status"),
    )


class OrderItem(Base):
    """A single line in an order (a product and requested quantity).

    - order_id: FK to Order
    - product_id: FK to Product

    - unit_price: denormalized price at time of ordering
    - quantity: how many units (kg or pieces) the customer requested
    - subtotal: unit_price * quantity (denormalized)

    Reasoning: Denormalized prices allow price changes after order creation without affecting historical orders.
    """
    __tablename__ = "order_item"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id", ondelete="RESTRICT"), nullable=False)


    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Float, nullable=False)
    subtotal = Column(Numeric(10, 2), nullable=False)

    # relationships
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")



class Payment(Base):
    """Payment attempts and records for an order.

    - order_id: FK to Order
    - provider: textual name if multiple payment providers in future
    - amount: paid amount
    - status: pending/success/failed/refunded
    - transaction_id: provider transaction reference to reconcile

    Reasoning: Payments are in a separate table because there might be multiple attempts, refunds, or partial payments.
    """
    __tablename__ = "payment"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(100), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(SAEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    transaction_id = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationship
    order = relationship("Order", back_populates="payments")


# -----------------
# Delivery handling
# -----------------

class Delivery(Base):
    """Represents a delivery attempt/assignment for an order.

    - We separate Delivery from Order to allow:
      * Multiple attempts (e.g. first attempt failed, second attempt made)
      * Assigning a courier and tracking pickup/delivery timestamps and statuses
    - courier_id: FK to Courier (nullable until assigned)
    - order_id: FK to Order (one-to-many: one order can have multiple deliveries over time)
    - scheduled_at: optional scheduled pickup time
    - picked_up_at / delivered_at: timestamps recorded by courier
    - fee: any additional delivery fee captured at assignment time
    """
    __tablename__ = "delivery"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("courier.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(SAEnum(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING)
    scheduled_at = Column(DateTime, nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    picked_up_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    failed_reason = Column(Text, nullable=True)
    fee = Column(Numeric(8, 2), nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationships
    order = relationship("Order", back_populates="deliveries")
    courier = relationship("Courier", back_populates="deliveries")


# -----------------
# Optional: Reviews
# -----------------
class Review(Base):
    """Customer reviews for delivered orders/products.

    - order_id: FK to Order (link review to an order)
    - product_id: FK to Product (optional) if review is about a specific product
    - rating: integer rating, comment: textual feedback
    """
    __tablename__ = "review"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    product_id = Column(Integer, ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="SET NULL"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # relationships (optional)
    # We intentionally do not create back_populates for reviews to keep them lightweight; add if you need.


# -----------------
# Helpful utility functions
# -----------------

def calculate_order_totals(order):
    """Fill order.total_amount and each item.subtotal based on unit_price and quantity.

    - This is a simple helper; in real code, you should also consider taxes, discounts, rounding rules, and
      currency considerations.
    - Should be called before persisting an order if items changed.
    """
    total = 0
    for item in order.items:
        item.subtotal = float(item.unit_price) * float(item.quantity)
        total += item.subtotal
    order.total_amount = round(total, 2)


# End of file
