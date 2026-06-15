from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    sql: Dict[str, Any] = Field(default_factory=dict)
    vector: Dict[str, Any] = Field(default_factory=dict)
