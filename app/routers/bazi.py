import re
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Literal, Optional, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
import requests
from lunar_python import Solar, Lunar
from lunar_python.eightchar import Yun
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user_or_401
# from ..security import get_current_user
from ..schemas_old import BaziComputeRequest, BaziComputeResponse
from ..services.bazi import compute_bazi_demo, bazi_fingerprint
from .. import models
from ..utils import geo_amap
from app.models.chat import Conversation, Message
from app.models.profile import UserProfile
from app.core.logging import get_logger

logger = get_logger("bazi")

Gender = Literal["男", "女"]
Calendar = Literal["gregorian", "lunar"]

router = APIRouter(prefix="/bazi", tags=["bazi"])

WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
STEM_ELEMENTS = {
    "甲": "wood",
    "乙": "wood",
    "丙": "fire",
    "丁": "fire",
    "戊": "earth",
    "己": "earth",
    "庚": "metal",
    "辛": "metal",
    "壬": "water",
    "癸": "water",
}
ELEMENT_CN = {
    "wood": "木",
    "fire": "火",
    "earth": "土",
    "metal": "金",
    "water": "水",
}

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


def _build_today_lunar_info() -> Dict[str, Any]:
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    solar = Solar.fromYmdHms(today.year, today.month, today.day, today.hour, today.minute, today.second)
    lunar = solar.getLunar()

    lunar_month = lunar.getMonthInChinese()
    lunar_day = lunar.getDayInChinese()
    lunar_date = f"农历{lunar_month}月{lunar_day}"
    ganzhi = {
        "year": lunar.getYearInGanZhi(),
        "month": lunar.getMonthInGanZhi(),
        "day": lunar.getDayInGanZhi(),
    }
    weekday = WEEKDAYS_CN[today.weekday()]

    return {
        "solar_date": today.strftime("%Y-%m-%d"),
        "lunar_date": lunar_date,
        "ganzhi": ganzhi,
        "weekday": weekday,
        "display": f"{lunar_date} · {ganzhi['year']}年 {ganzhi['month']}月 {ganzhi['day']}日 · {weekday}",
    }


def _get_day_master_from_chart(chart: Optional[dict]) -> Optional[str]:
    if not chart:
        return None

    try:
        mingpan = chart.get("mingpan", chart)
        four_pillars = mingpan.get("four_pillars", {})
        day = four_pillars.get("day")
        if isinstance(day, list) and day:
            return str(day[0]) or None
        if isinstance(day, dict):
            for key in ("stem", "gan"):
                value = day.get(key)
                if isinstance(value, str) and value:
                    return value
    except Exception:
        return None

    return None


def _infer_recent_focus(db: Session, user_id: int) -> str:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(5)
        .all()
    )

    texts: List[str] = []
    for conv in conversations:
        task_context = conv.task_context or {}
        task_type = task_context.get("taskType") or task_context.get("task_type")
        title = task_context.get("title") or conv.title
        if task_type:
            texts.append(str(task_type))
        if title:
            texts.append(str(title))

        messages = (
            db.query(Message.content)
            .filter(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.id.desc())
            .limit(3)
            .all()
        )
        texts.extend(content for (content,) in messages if content)

    haystack = "\n".join(texts)
    if re.search(r"offer|工作|事业|跳槽|岗位|创业|合作|老板|同事|薪资|升职", haystack, re.I):
        return "career"
    if re.search(r"感情|关系|复合|分手|对象|伴侣|婚姻|恋爱|回复|暧昧", haystack):
        return "relationship"
    if re.search(r"财|钱|收入|投资|订单|客户|资源|预算|付款|回款", haystack):
        return "wealth"
    if re.search(r"房子|工位|搬家|居住|租房|办公室|风水|方位", haystack):
        return "space"
    return "rhythm"


def _build_reminder_payload(
    focus: str,
    lunar_info: Dict[str, Any],
    day_master: Optional[str],
) -> Dict[str, Any]:
    day_ganzhi = lunar_info["ganzhi"]["day"]
    day_stem = day_ganzhi[:1]
    day_element = STEM_ELEMENTS.get(day_stem)
    element_text = ELEMENT_CN.get(day_element, "")

    rules = {
        "career": {
            "theme": "机会与边界",
            "title": "事业与节奏",
            "suitable_actions": ["梳理岗位条件", "补充关键信息", "低压力沟通"],
            "caution_actions": ["立刻承诺", "情绪化拒绝", "忽略成本"],
            "reminder": "先把想要和能承受分开看。",
            "closing_sentence": "如果你正在看工作或合作，今天适合把条件问清楚，不急着给出最终答案。",
        },
        "relationship": {
            "theme": "关系与分寸",
            "title": "关系与节奏",
            "suitable_actions": ["观察实际行动", "温和表达需求", "放慢判断"],
            "caution_actions": ["逼问结果", "反复试探", "替对方下结论"],
            "reminder": "先看对方做了什么，再决定自己说多少。",
            "closing_sentence": "如果你正在处理关系问题，今天适合把话说轻一点，把观察放具体一点。",
        },
        "wealth": {
            "theme": "资源与选择",
            "title": "资源与节奏",
            "suitable_actions": ["核对钱款", "整理机会", "确认承诺"],
            "caution_actions": ["情绪化消费", "仓促投入", "一次定死"],
            "reminder": "先看资源怎么流动，再决定下一步。",
            "closing_sentence": "今天适合核对资源与承诺，不急着把选择一次定死。",
        },
        "space": {
            "theme": "环境与安定",
            "title": "空间与节奏",
            "suitable_actions": ["整理桌面", "观察动线", "确认实际需求"],
            "caution_actions": ["大幅改动", "冲动签约", "只看感觉"],
            "reminder": "先让环境服务现实需求。",
            "closing_sentence": "如果你正在看房子、工位或布局，今天适合先确认使用习惯，再做调整。",
        },
        "rhythm": {
            "theme": "先整理，再行动",
            "title": "节律与整理",
            "suitable_actions": ["梳理计划", "补充资料", "低压力沟通"],
            "caution_actions": ["冲动承诺", "情绪化判断", "一次定死"],
            "reminder": "先把乱的部分理顺，再决定下一步。",
            "closing_sentence": "今天不一定要推进很多，但适合先把心里乱的部分理顺。",
        },
    }
    base = rules.get(focus, rules["rhythm"]).copy()

    if day_master and day_element:
        base["basis"] = f"今日为{day_ganzhi}日，日干属{element_text}；结合你的日主与最近关注主题生成。"
    else:
        base["basis"] = f"今日为{day_ganzhi}日；结合最近关注主题生成。"

    return {
        **base,
        "focus": focus,
        "day_master": day_master,
        "day_ganzhi": day_ganzhi,
        "lunar_display": lunar_info["display"],
        "lunar": lunar_info,
    }


@router.get("/today_lunar")
def get_today_lunar():
    """Return today's lunar calendar summary using lunar-python."""
    return _build_today_lunar_info()


@router.get("/today_reminder")
def get_today_reminder(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    """Return a low-pressure daily reminder based on profile and recent focus."""
    lunar_info = _build_today_lunar_info()
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    day_master = _get_day_master_from_chart(profile.bazi_chart if profile else None)
    focus = _infer_recent_focus(db, user_id)
    return _build_reminder_payload(focus, lunar_info, day_master)

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
    logger.info("calc_paipan_request", gender=body.gender, birth_date=body.birth_date, birthplace=body.birthplace)
    try:
        # 1) 解析时间
        birthday_adjusted = to_birthday_adjusted(body)
        dt_obj = datetime.strptime(birthday_adjusted, "%Y-%m-%d %H:%M:%S")

        # 2) 根据 calendar 类型获取 Lunar 对象
        if body.calendar == "lunar":
            # 农历输入：直接使用 Lunar.fromYmdHms() 创建农历对象
            lunar = Lunar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day,
                                     dt_obj.hour, dt_obj.minute, dt_obj.second)
        else:
            # 公历输入：先创建 Solar 对象，再转换为 Lunar
            solar = Solar.fromYmdHms(dt_obj.year, dt_obj.month, dt_obj.day,
                                     dt_obj.hour, dt_obj.minute, dt_obj.second)
            lunar = solar.getLunar()

        # 3) 四柱（清洗成 ["干","支"]）
        # 注意：必须使用 EightChar 类来获取八字四柱，而不是 Lunar 类
        # - lunar.getXxxInGanZhi() 返回的是农历干支（以正月初一为年界，以农历月为月界）
        # - eightChar.getXxx() 返回的是八字干支（以立春为年界，以节气为月界）
        eight_char = lunar.getEightChar()
        four_pillars = {
            "year":  _split_ganzhi_to_list(eight_char.getYear()),
            "month": _split_ganzhi_to_list(eight_char.getMonth()),
            "day":   _split_ganzhi_to_list(eight_char.getDay()),
            "hour":  _split_ganzhi_to_list(eight_char.getTime()),
        }

        # 4) 大运（复用上面已获取的 eight_char）
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

        logger.info("calc_paipan_completed", gender=body.gender, four_pillars=four_pillars)

        # 5) 返回同结构（含真太阳时校正后的公历日期，供 AI 直接引用）
        return {
            "mingpan": {
                "gender": body.gender,
                "four_pillars": four_pillars,
                "dayun": dayun_list,
                "solar_date": birthday_adjusted,   # "YYYY-MM-DD HH:MM:SS"（真太阳时）
            }
        }
    except Exception as e:
        logger.exception("calc_paipan_error", error=str(e))
        return {"error": f"{type(e).__name__}: {e}"}
