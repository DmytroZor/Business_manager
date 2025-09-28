from pydantic import BaseModel, Field, field_validator, computed_field
from typing import List


class CreateReview(BaseModel):
    rating:int = Field(..., ge = 0, le = 5)
    comment:str | None = Field(max_length=255)

