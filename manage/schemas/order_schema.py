from pydantic import BaseModel, Field, field_validator, computed_field
from typing import List
from decimal import Decimal, ROUND_DOWN
from product_schema import ProductOut


class OrderItemCreate(BaseModel):
    unit_price: Decimal = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        # округляємо до 2 знаків після коми
        v = v.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        # перевіряємо, чи після округлення не змінилось
        if v != v:
            raise ValueError("Неправильна точність quantity, максимум 2 знаки після коми")
        return v

    @computed_field
    @property
    def subtotal(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


class OrdersOut(BaseModel):
    items: List[OrderItemCreate] = []
    total_amount: Decimal  # сума всіх subtotal
