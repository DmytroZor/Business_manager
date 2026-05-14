"""add product last_purchase_at

Revision ID: c8a1d9e3f4b2
Revises: b12f5f4229d1
Create Date: 2026-05-06 18:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8a1d9e3f4b2"
down_revision: Union[str, Sequence[str], None] = "b12f5f4229d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product", sa.Column("last_purchase_at", sa.Date(), nullable=True))
    op.create_index(op.f("ix_product_last_purchase_at"), "product", ["last_purchase_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_product_last_purchase_at"), table_name="product")
    op.drop_column("product", "last_purchase_at")
