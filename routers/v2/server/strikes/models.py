from pydantic import BaseModel, Field
from typing import Optional, Union


class StrikeRequest(BaseModel):
    reason: str
    added_by: Union[int, str] = Field(description="Discord user ID who added the strike (can be string to preserve precision for large IDs)")
    rollover_days: Optional[int] = Field(None, description="Days until strike expires")
    strike_weight: int = Field(1, description="Weight/severity of the strike", ge=1)
    image: Optional[str] = Field(None, description="Optional image URL for evidence")


class StrikeResponse(BaseModel):
    strike_id: str
    tag: str
    date_created: str
    reason: str
    server: int
    added_by: Union[int, str]  # Can be string to preserve precision for large Discord IDs
    strike_weight: int
    rollover_date: Optional[int] = None
    image: Optional[str] = None
