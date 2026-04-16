# app/schemas/profile.py
from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ProfileCreateRequest(BaseModel):
    """创建用户档案请求"""
    gender: Literal["male", "female"] = Field(..., description="性别")
    calendar_type: Literal["solar", "lunar"] = Field(default="solar", description="历法类型")
    birth_date: date = Field(..., description="出生日期 YYYY-MM-DD")
    birth_time: time = Field(..., description="出生时间 HH:MM:SS")
    birth_location: str = Field(..., min_length=1, max_length=100, description="出生地点（城市名称）")
    birth_longitude: Optional[float] = Field(None, ge=-180, le=180, description="出生地经度")
    birth_latitude: Optional[float] = Field(None, ge=-90, le=90, description="出生地纬度")

    @field_validator("birth_location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        """验证地点不为空"""
        if not v.strip():
            raise ValueError("出生地点不能为空")
        return v.strip()


class ProfileUpdateRequest(BaseModel):
    """更新用户档案请求（所有字段可选）"""
    gender: Optional[Literal["male", "female"]] = None
    calendar_type: Optional[Literal["solar", "lunar"]] = None
    birth_date: Optional[date] = None
    birth_time: Optional[time] = None
    birth_location: Optional[str] = Field(None, min_length=1, max_length=100)
    birth_longitude: Optional[float] = Field(None, ge=-180, le=180)
    birth_latitude: Optional[float] = Field(None, ge=-90, le=90)


class ProfileResponse(BaseModel):
    """用户档案响应"""
    id: int
    user_id: int
    gender: str
    calendar_type: str
    birth_date: date
    birth_time: time
    birth_location: str
    birth_longitude: Optional[float]
    birth_latitude: Optional[float]
    bazi_chart: Optional[dict]
    created_at: datetime
    updated_at: datetime

    # 便捷字段
    display_info: str = Field(..., description="格式化的档案信息")
    birth_datetime_str: str = Field(..., description="格式化的出生日期时间")

    class Config:
        from_attributes = True


class ProfileBriefResponse(BaseModel):
    """用户档案简要信息（用于聊天页顶部显示）"""
    id: int
    gender: str
    birth_date: date
    birth_time: time
    birth_location: str
    display_info: str

    class Config:
        from_attributes = True
