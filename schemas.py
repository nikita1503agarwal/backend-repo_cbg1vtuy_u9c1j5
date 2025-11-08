"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

class Customer(BaseModel):
    """Collection: customer"""
    name: str = Field(..., description="Full name")
    phone: str = Field(..., description="Phone number")
    email: str = Field(..., description="Email address")

class Vehicle(BaseModel):
    """Collection: vehicle"""
    customer_id: str = Field(..., description="Reference to customer _id as string")
    vin: str = Field(..., description="Vehicle Identification Number")
    plate: str = Field(..., description="License plate")
    make: str = Field(...)
    model: str = Field(...)
    year: int = Field(..., ge=1900, le=2100)
    color: Optional[str] = Field(None)

class Inspection(BaseModel):
    """Collection: inspection"""
    customer_id: str = Field(...)
    vehicle_id: str = Field(...)
    checks: Dict[str, Dict[str, str]] = Field(..., description="section -> item -> status(ok|attention|fail)")
    notes: Optional[str] = None
    photos: List[str] = []
    status: str = Field("inspection_complete")

class Invoice(BaseModel):
    """Collection: invoice"""
    inspection_id: str = Field(...)
    line_items: List[Dict[str, Any]]
    subtotal: float
    taxes: float
    total: float
    paid: bool = False
