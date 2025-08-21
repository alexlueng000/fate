import re
import json
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
import requests
from lunar_python import Solar
from lunar_python.eightchar import Yun
from sqlalchemy.orm import Session
from ..db import get_db
# from ..security import get_current_user
from ..schemas import BaziComputeRequest, BaziComputeResponse
from ..services.bazi import compute_bazi_demo, bazi_fingerprint
from .. import models

router = APIRouter(prefix="/bazi", tags=["bazi"])

# 地名 -> 经纬度
def geocode_city(city: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city, "format": "json", "limit": 1}
    headers = {"User-Agent": "bazi-app/1.0"}  # Nominatim 要求设置 UA
    r = requests.get(url, params=params, headers=headers)
    data = r.json()
    if not data:
        return {"error": f"找不到城市: {city}"}
    return {
        "city": city,
        "lat": float(data[0]["lat"]),
        "lng": float(data[0]["lon"])
    }


#========================================
# 真太阳时计算 COZE版
#========================================

class SolarIn(BaseModel):
    birth_date: str   # "YYYY-MM-DD HH:MM:SS"
    longitude: float  # 经度（东经为正，西经为负）


def calc_true_solar(body: SolarIn):
    try:
        # 解析输入时间
        dt = datetime.strptime(body.birth_date, "%Y-%m-%d %H:%M:%S")
        
        # 标准子午线经度（中国默认120°E）
        ref_longitude = 120.0

        # 每1度 = 4分钟
        delta_minutes = (body.longitude - ref_longitude) * 4
        dt_true = dt + timedelta(minutes=delta_minutes)

        return {
            "input_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "longitude": body.longitude,
            "true_solar_time": dt_true.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {"error": str(e)}


class PaipanIn(BaseModel):
    gender: str              # "男" 或 "女"
    birthday_adjusted: str   # "YYYY-MM-DD HH:MM:SS"

@router.post("/calc")
def calc_bazi(body: PaipanIn):
    try:
        # 1. 解析输入
        dt_obj = datetime.strptime(body.birthday_adjusted, "%Y-%m-%d %H:%M:%S")

        # 2. 转换为 Solar/Lunar
        solar = Solar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day,
                                 dt_obj.hour, dt_obj.minute, dt_obj.second)
        lunar = solar.getLunar()

        # 3. 四柱
        four_pillars = {
            "year": list(lunar.getYearInGanZhi()),
            "month": list(lunar.getMonthInGanZhi()),
            "day": list(lunar.getDayInGanZhi()),
            "hour": list(lunar.getTimeInGanZhi())
        }

        # 4. 大运
        eight_char = lunar.getEightChar()
        gender_code = 1 if body.gender == "男" else 0
        yun = Yun(eight_char, gender_code)
        dayun_list = []
        for du in yun.getDaYun():
            dayun_list.append({
                "age": du.getStartAge(),
                "start_year": du.getStartYear(),
                "pillar": list(du.getGanZhi())
            })

        # 5. 返回结果
        return {
            "mingpan": {
                "four_pillars": four_pillars,
                "dayun": dayun_list
            }
        }
    except Exception as e:
        return {"error": str(e)}
