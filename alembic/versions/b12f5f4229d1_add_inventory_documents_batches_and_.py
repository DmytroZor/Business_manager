"""add inventory documents batches and reserved stock

Revision ID: b12f5f4229d1
Revises: 89323c8591e7
Create Date: 2026-05-04 16:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b12f5f4229d1"
down_revision: Union[str, Sequence[str], None] = "89323c8591e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


stockdocumenttype = postgresql.ENUM(
    "RECEIPT",
    "ADJUSTMENT",
    "INVENTORY_COUNT",
    name="stockdocumenttype",
)


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _check_constraint_names(inspector, table_name: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_check_constraints(table_name) if constraint.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    stockdocumenttype.create(bind, checkfirst=True)

    product_columns = _column_names(inspector, "product")
    product_constraints = _check_constraint_names(inspector, "product")

    if "last_purchase_price" not in product_columns:
        op.add_column("product", sa.Column("last_purchase_price", sa.Numeric(10, 2), nullable=True))
    if "reserved_quantity" not in product_columns:
        op.add_column(
            "product",
            sa.Column("reserved_quantity", sa.Numeric(10, 3), nullable=False, server_default="0"),
        )
        op.alter_column("product", "reserved_quantity", server_default=None)

    if "ck_product_reserved_quantity_non_negative" not in product_constraints:
        op.create_check_constraint(
            "ck_product_reserved_quantity_non_negative",
            "product",
            "reserved_quantity >= 0",
        )
    if "ck_product_last_purchase_price_positive" not in product_constraints:
        op.create_check_constraint(
            "ck_product_last_purchase_price_positive",
            "product",
            "last_purchase_price IS NULL OR last_purchase_price > 0",
        )

    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "supplier"):
        op.create_table(
            "supplier",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("email", sa.String(length=200), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
    supplier_indexes = _index_names(sa.inspect(bind), "supplier")
    if op.f("ix_supplier_name") not in supplier_indexes:
        op.create_index(op.f("ix_supplier_name"), "supplier", ["name"], unique=False)

    if not _table_exists(sa.inspect(bind), "stock_document"):
        op.create_table(
            "stock_document",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("document_number", sa.String(length=100), nullable=False),
            sa.Column("document_type", stockdocumenttype, nullable=False),
            sa.Column("document_date", sa.Date(), nullable=False),
            sa.Column("supplier_id", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    stock_document_indexes = _index_names(sa.inspect(bind), "stock_document")
    for index_name, columns in [
        (op.f("ix_stock_document_created_by_user_id"), ["created_by_user_id"]),
        (op.f("ix_stock_document_document_date"), ["document_date"]),
        (op.f("ix_stock_document_document_number"), ["document_number"]),
        (op.f("ix_stock_document_supplier_id"), ["supplier_id"]),
        ("ix_stock_document_type_date", ["document_type", "document_date"]),
    ]:
        if index_name not in stock_document_indexes:
            op.create_index(index_name, "stock_document", columns, unique=False)

    if not _table_exists(sa.inspect(bind), "stock_document_item"):
        op.create_table(
            "stock_document_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("document_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("product_name", sa.String(length=200), nullable=False),
            sa.Column("unit", sa.String(length=20), nullable=False),
            sa.Column("quantity_value", sa.Numeric(10, 3), nullable=False),
            sa.Column("applied_delta", sa.Numeric(10, 3), nullable=False, server_default="0"),
            sa.Column("sale_unit_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("purchase_unit_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("batch_code", sa.String(length=100), nullable=True),
            sa.Column("serial_code", sa.String(length=100), nullable=True),
            sa.Column("expires_at", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "sale_unit_price IS NULL OR sale_unit_price > 0",
                name="ck_stock_document_item_sale_price_positive",
            ),
            sa.CheckConstraint(
                "purchase_unit_price IS NULL OR purchase_unit_price > 0",
                name="ck_stock_document_item_purchase_price_positive",
            ),
            sa.ForeignKeyConstraint(["document_id"], ["stock_document.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.alter_column("stock_document_item", "applied_delta", server_default=None)
    stock_document_item_indexes = _index_names(sa.inspect(bind), "stock_document_item")
    for index_name, columns in [
        (op.f("ix_stock_document_item_document_id"), ["document_id"]),
        (op.f("ix_stock_document_item_product_id"), ["product_id"]),
    ]:
        if index_name not in stock_document_item_indexes:
            op.create_index(index_name, "stock_document_item", columns, unique=False)

    if not _table_exists(sa.inspect(bind), "product_batch"):
        op.create_table(
            "product_batch",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("supplier_id", sa.Integer(), nullable=True),
            sa.Column("stock_document_id", sa.Integer(), nullable=True),
            sa.Column("stock_document_item_id", sa.Integer(), nullable=True),
            sa.Column("batch_code", sa.String(length=100), nullable=True),
            sa.Column("serial_code", sa.String(length=100), nullable=True),
            sa.Column("expires_at", sa.Date(), nullable=True),
            sa.Column("purchase_unit_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("original_quantity", sa.Numeric(10, 3), nullable=False, server_default="0"),
            sa.Column("available_quantity", sa.Numeric(10, 3), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("original_quantity >= 0", name="ck_product_batch_original_quantity_non_negative"),
            sa.CheckConstraint("available_quantity >= 0", name="ck_product_batch_available_quantity_non_negative"),
            sa.CheckConstraint(
                "purchase_unit_price IS NULL OR purchase_unit_price > 0",
                name="ck_product_batch_purchase_price_positive",
            ),
            sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["stock_document_id"], ["stock_document.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["stock_document_item_id"], ["stock_document_item.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.alter_column("product_batch", "original_quantity", server_default=None)
        op.alter_column("product_batch", "available_quantity", server_default=None)
    product_batch_indexes = _index_names(sa.inspect(bind), "product_batch")
    for index_name, columns in [
        (op.f("ix_product_batch_batch_code"), ["batch_code"]),
        (op.f("ix_product_batch_expires_at"), ["expires_at"]),
        (op.f("ix_product_batch_product_id"), ["product_id"]),
        ("ix_product_batch_product_expiry_received", ["product_id", "expires_at", "received_at"]),
        (op.f("ix_product_batch_serial_code"), ["serial_code"]),
        (op.f("ix_product_batch_stock_document_id"), ["stock_document_id"]),
        (op.f("ix_product_batch_stock_document_item_id"), ["stock_document_item_id"]),
        (op.f("ix_product_batch_supplier_id"), ["supplier_id"]),
    ]:
        if index_name not in product_batch_indexes:
            op.create_index(index_name, "product_batch", columns, unique=False)

    if not _table_exists(sa.inspect(bind), "order_item_batch_allocation"):
        op.create_table(
            "order_item_batch_allocation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("order_item_id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("quantity > 0", name="ck_order_item_batch_allocation_quantity_positive"),
            sa.ForeignKeyConstraint(["batch_id"], ["product_batch.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["order_item_id"], ["order_item.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    allocation_indexes = _index_names(sa.inspect(bind), "order_item_batch_allocation")
    for index_name, columns in [
        (op.f("ix_order_item_batch_allocation_batch_id"), ["batch_id"]),
        (op.f("ix_order_item_batch_allocation_order_item_id"), ["order_item_id"]),
    ]:
        if index_name not in allocation_indexes:
            op.create_index(index_name, "order_item_batch_allocation", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "order_item_batch_allocation"):
        allocation_indexes = _index_names(inspector, "order_item_batch_allocation")
        if op.f("ix_order_item_batch_allocation_order_item_id") in allocation_indexes:
            op.drop_index(op.f("ix_order_item_batch_allocation_order_item_id"), table_name="order_item_batch_allocation")
        if op.f("ix_order_item_batch_allocation_batch_id") in allocation_indexes:
            op.drop_index(op.f("ix_order_item_batch_allocation_batch_id"), table_name="order_item_batch_allocation")
        op.drop_table("order_item_batch_allocation")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "product_batch"):
        product_batch_indexes = _index_names(inspector, "product_batch")
        for index_name in [
            op.f("ix_product_batch_supplier_id"),
            op.f("ix_product_batch_stock_document_item_id"),
            op.f("ix_product_batch_stock_document_id"),
            op.f("ix_product_batch_serial_code"),
            "ix_product_batch_product_expiry_received",
            op.f("ix_product_batch_product_id"),
            op.f("ix_product_batch_expires_at"),
            op.f("ix_product_batch_batch_code"),
        ]:
            if index_name in product_batch_indexes:
                op.drop_index(index_name, table_name="product_batch")
        op.drop_table("product_batch")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "stock_document_item"):
        stock_document_item_indexes = _index_names(inspector, "stock_document_item")
        for index_name in [
            op.f("ix_stock_document_item_product_id"),
            op.f("ix_stock_document_item_document_id"),
        ]:
            if index_name in stock_document_item_indexes:
                op.drop_index(index_name, table_name="stock_document_item")
        op.drop_table("stock_document_item")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "stock_document"):
        stock_document_indexes = _index_names(inspector, "stock_document")
        for index_name in [
            "ix_stock_document_type_date",
            op.f("ix_stock_document_supplier_id"),
            op.f("ix_stock_document_document_number"),
            op.f("ix_stock_document_document_date"),
            op.f("ix_stock_document_created_by_user_id"),
        ]:
            if index_name in stock_document_indexes:
                op.drop_index(index_name, table_name="stock_document")
        op.drop_table("stock_document")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "supplier"):
        supplier_indexes = _index_names(inspector, "supplier")
        if op.f("ix_supplier_name") in supplier_indexes:
            op.drop_index(op.f("ix_supplier_name"), table_name="supplier")
        op.drop_table("supplier")

    product_columns = _column_names(sa.inspect(bind), "product")
    product_constraints = _check_constraint_names(sa.inspect(bind), "product")
    if "ck_product_last_purchase_price_positive" in product_constraints:
        op.drop_constraint("ck_product_last_purchase_price_positive", "product", type_="check")
    if "ck_product_reserved_quantity_non_negative" in product_constraints:
        op.drop_constraint("ck_product_reserved_quantity_non_negative", "product", type_="check")
    if "reserved_quantity" in product_columns:
        op.drop_column("product", "reserved_quantity")
    if "last_purchase_price" in product_columns:
        op.drop_column("product", "last_purchase_price")

    stockdocumenttype.drop(bind, checkfirst=True)
