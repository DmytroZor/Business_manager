from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

class CreateReview(BaseModel):
    product_id: Optional[int] = Field(
        default=None,
        gt=0,
        description="Optional product ID if the review is about a specific product",
    )
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    comment: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional customer comment",
    )


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: Optional[int]
    product_id: Optional[int]
    customer_id: Optional[int]
    rating: int
    comment: Optional[str]
    created_at: datetime