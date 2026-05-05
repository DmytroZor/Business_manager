"""add product inventory and image fields

Revision ID: f9b3c7a8d2e1
Revises: c4d9e2a1f6b3
Create Date: 2026-04-29 19:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9b3c7a8d2e1"
down_revision: Union[str, Sequence[str], None] = "c4d9e2a1f6b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column(
        "product",
        sa.Column("available_quantity", sa.Numeric(10, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_product_available_quantity_non_negative",
        "product",
        "available_quantity >= 0",
    )
    op.alter_column("product", "available_quantity", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_product_available_quantity_non_negative", "product", type_="check")
    op.drop_column("product", "available_quantity")
    op.drop_column("product", "image_url")
