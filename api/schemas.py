# api/schemas.py
from __future__ import annotations

from typing import Generic, Optional, TypeVar, Any, Dict
from pydantic import BaseModel
from pydantic.generics import GenericModel

T = TypeVar("T")

class Meta(BaseModel):
    request_id: str
    count: Optional[int] = None
    next_cursor: Optional[str] = None

class ApiResponse(GenericModel, Generic[T]):
    ok: bool = True
    data: T
    meta: Meta
    error: Optional[Dict[str, Any]] = None