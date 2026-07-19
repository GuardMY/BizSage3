"""Shared API response model behavior."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_serializer

from app.time_utils import serialize_shanghai


class ShanghaiTimeResponseModel(BaseModel):
    """Serialize every datetime field in API responses as Asia/Shanghai."""

    @field_serializer("*", mode="wrap", check_fields=False)
    def serialize_datetime(self, value: Any, handler: Any) -> Any:
        if isinstance(value, datetime):
            return serialize_shanghai(value)
        return handler(value)
