import re
import json
from datetime import datetime, timedelta
from typing import Literal, Optional, List

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
from ..utils import geo_amap

Gender = Literal["男", "女"]
Calendar = Literal["gregorian", "lunar"]

router = APIRouter(prefix="/bazi", tags=["bazi"])

#========================================
# COZE版代码
#========================================


# 地名 -> 经纬度

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
    birthday_adjusted: str   # "YYYY-MM-DD HH:MM:SS" 通过经纬度算出来的真太阳时


def _split_ganzhi_to_list(gz: str) -> List[str]:
    """
    将 '癸酉' / '  壬子 ' / '' 等转成 ['癸','酉'] 或 []，并去除异常空格。
    lunar_python 的 getXxxInGanZhi() 返回的是字符串，例如 '癸酉'。
    """
    if gz is None:
        return []
    s = str(gz).strip().replace(" ", "")
    # 标准干支长度应为2（一个天干+一个地支）
    return [s[0], s[1]] if len(s) == 2 else []

class PaipanIn(BaseModel):
    gender: Gender                         # "男" / "女"
    calendar: Calendar = "gregorian"       # 前端下拉：公历/农历（暂未用到农历换算时可先保留）
    birth_date: str = Field(..., description="YYYY-MM-DD")
    birth_time: str = Field(..., description="HH:MM")  # 24小时制
    birthplace: str = Field(..., description="城市名称，如：广东阳春")
    use_true_solar: bool = True           # 是否启用真太阳时（默认不启用）

    # 可选直传（若前端已拿到经纬度，可跳过地名解析）
    lat: Optional[float] = None
    lng: Optional[float] = None
    # 可选：若你支持自带经度修正，允许直接传经度
    longitude: Optional[float] = None

def compose_local_dt_str(date_str: str, time_str: str) -> str:
    """把 YYYY-MM-DD + HH:MM -> 'YYYY-MM-DD HH:MM:SS'"""
    # 统一补秒，避免解析问题
    return f"{date_str.strip()} {time_str.strip()}:00"

def to_birthday_adjusted(inb: PaipanIn) -> str:
    """
    计算 birthday_adjusted（真太阳时 or 本地时）
    返回格式：'YYYY-MM-DD HH:MM:SS'
    """
    # 1) 本地时
    local_dt = compose_local_dt_str(inb.birth_date, inb.birth_time)

    if not inb.use_true_solar:
        return local_dt

    # 2) 经度来源：优先 longitude，再 lng，再地名解析
    longitude = None
    if inb.longitude is not None:
        longitude = inb.longitude
    elif inb.lng is not None:
        longitude = inb.lng
    else:
        geo = geo_amap.geocode_city(inb.birthplace)
        if "error" in geo:
            # 回退成“本地时”，也可以选择抛错
            # raise HTTPException(400, f"地名解析失败：{geo['error']}")
            return local_dt
        longitude = geo["lng"]

    # 3) 真太阳时换算（经度修正简化版）
    ts = calc_true_solar(SolarIn(birth_date=local_dt, longitude=longitude))
    if "true_solar_time" in ts:
        return ts["true_solar_time"]
    # 失败回退：返回本地时
    return local_dt


@router.post("/calc_paipan")
def calc_bazi(body: PaipanIn):
    """
    入参 body 需要有:
    - body.gender: '男' 或 '女'
    - body.birthday_adjusted: 'YYYY-MM-DD HH:MM:SS'
    返回:
    {
      "mingpan": {
        "four_pillars": { "year": [...], "month": [...], "day": [...], "hour": [...] },
        "dayun": [ {"age":..,"start_year":..,"pillar":[...]} ... ]
      }
    }
    """
    print("输入参数：", body)
    try:
        # 1) 解析时间
        birthday_adjusted = to_birthday_adjusted(body)
        dt_obj = datetime.strptime(birthday_adjusted, "%Y-%m-%d %H:%M:%S")

        # 2) 公历 -> Lunar
        solar = Solar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day,
                                 dt_obj.hour, dt_obj.minute, dt_obj.second)
        lunar = solar.getLunar()

        # 3) 四柱（清洗成 ["干","支"]）
        four_pillars = {
            "year":  _split_ganzhi_to_list(lunar.getYearInGanZhi()),
            "month": _split_ganzhi_to_list(lunar.getMonthInGanZhi()),
            "day":   _split_ganzhi_to_list(lunar.getDayInGanZhi()),
            "hour":  _split_ganzhi_to_list(lunar.getTimeInGanZhi()),
        }

        # 4) 大运
        eight_char = lunar.getEightChar()
        gender_code = 1 if str(body.gender).strip() == "男" else 0
        yun = Yun(eight_char, gender_code)

        dayun_list = []
        for du in yun.getDaYun():
            pillar_list = _split_ganzhi_to_list(du.getGanZhi())
            dayun_list.append({
                "age": du.getStartAge(),
                "start_year": du.getStartYear(),
                "pillar": pillar_list  # 若库返回异常或空，会是 []
            })

        print("输出结果：", {"mingpan": {"four_pillars": four_pillars, "dayun": dayun_list}})

        # 5) 返回同结构
        return {
            "mingpan": {
                "four_pillars": four_pillars,
                "dayun": dayun_list
            }
        }
    except Exception as e:
        print("出错：", e)
        return {"error": f"{type(e).__name__}: {e}"}