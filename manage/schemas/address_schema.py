from pydantic import BaseModel, Field
from typing import Optional


class AddressBase(BaseModel):
    street: str = Field(..., max_length=255, description="Street name.")
    building: str = Field(..., min_length=1, max_length=20, description="Building identifier, for example 10A.")
    apartment: Optional[str] = Field(None, max_length=20, description="Apartment, office, or unit number.")
    notes: Optional[str] = Field(None, description="Optional delivery notes.")


class AddressCreate(AddressBase):
    """Schema for address creation."""
    pass


class AddressUpdate(BaseModel):
    """Schema for address updates (all fields optional)."""
    street: Optional[str] = Field(None, max_length=255, description="Updated street name.")
    building: Optional[str] = Field(None, min_length=1, max_length=20, description="Updated building identifier.")
    apartment: Optional[str] = Field(None, max_length=20, description="Updated apartment or unit.")
    notes: Optional[str] = Field(None, description="Updated delivery notes.")


class AddressOut(AddressBase):
    """Schema returned by address endpoints."""
    id: int = Field(..., description="Address identifier.")
    customer_id: int = Field(..., description="Customer profile identifier.")

    class Config:
        from_attributes = True
