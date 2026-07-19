"""Shared API response model behavior."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, field_serializer

from app.time_utils import serialize_shanghai


class ShanghaiTimeResponseModel(BaseModel):
    """Serialize every datetime field in API responses as Asia/Shanghai."""

    @field_serializer("*", mode="wrap", check_fields=False)
    def serialize_datetime(self, value: Any, handler: Any) -> Any:
        if isinstance(value, datetime):
            return serialize_shanghai(value)
        return handler(value)


ResponseItem = TypeVar("ResponseItem")


class PaginatedResponse(ShanghaiTimeResponseModel, Generic[ResponseItem]):
    """Standard envelope for server-side paginated list endpoints."""

    items: list[ResponseItem]
    page: int
    page_size: int
    total: int
