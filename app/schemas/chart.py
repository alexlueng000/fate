# app/schemas/chart.py
from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime


class SaveChartRequest(BaseModel):
    name: str
    birth_info: dict[str, Any]
    chart_data: dict[str, Any]


class ChartListItem(BaseModel):
    id: int
    name: str
    is_default: bool
    created_at: str


class ChartListResponse(BaseModel):
    charts: list[ChartListItem]


class ChartDetailResponse(BaseModel):
    id: int
    name: str
    birth_info: dict[str, Any]
    chart_data: dict[str, Any]
    is_default: bool
    created_at: str


class SaveChartResponse(BaseModel):
    id: int
    name: str
    is_default: bool
    created_at: str
