from pydantic import BaseModel, Field
from datetime import datetime
from typing import List

class EventCreate(BaseModel):
    name: str
    sale_start_time: datetime
    rows: int = Field(ge=1, le=26)
    seats_per_row: int = Field(ge=1)

class EventResponse(BaseModel):
    id: int
    name: str
    sale_start_time: datetime
    rows: int
    seats_per_row: int

    model_config = {"from_attributes": True}

class BuyRequest(BaseModel):
    user_id: str
    event_id: int
    seat_numbers: List[str] = Field(min_length=1, max_length=5)

class BuyResponse(BaseModel):
    message: str
    seat_numbers: List[str]