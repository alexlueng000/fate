# app/utils/solar_terms.py
"""
24节气计算工具
根据日期计算当前节气和五行属性
"""
from datetime import datetime
from typing import Tuple, Optional

# 24节气数据：[节气名, 月份, 大致日期范围起始]
SOLAR_TERMS = [
    ("立春", 2, 3), ("雨水", 2, 18), ("惊蛰", 3, 5), ("春分", 3, 20),
    ("清明", 4, 4), ("谷雨", 4, 19), ("立夏", 5, 5), ("小满", 5, 20),
    ("芒种", 6, 5), ("夏至", 6, 21), ("小暑", 7, 6), ("大暑", 7, 22),
    ("立秋", 8, 7), ("处暑", 8, 22), ("白露", 9, 7), ("秋分", 9, 22),
    ("寒露", 10, 8), ("霜降", 10, 23), ("立冬", 11, 7), ("小雪", 11, 22),
    ("大雪", 12, 6), ("冬至", 12, 21), ("小寒", 1, 5), ("大寒", 1, 20),
]

# 节气到五行的映射（简化版本）
TERM_TO_WUXING = {
    "立春": "木", "雨水": "木", "惊蛰": "木", "春分": "木",
    "清明": "木", "谷雨": "土",
    "立夏": "火", "小满": "火", "芒种": "火", "夏至": "火",
    "小暑": "火", "大暑": "土",
    "立秋": "金", "处暑": "金", "白露": "金", "秋分": "金",
    "寒露": "金", "霜降": "土",
    "立冬": "水", "小雪": "水", "大雪": "水", "冬至": "水",
    "小寒": "水", "大寒": "土",
}


def get_solar_term(date: datetime) -> Tuple[str, str]:
    """
    根据日期获取当前节气和五行属性

    Args:
        date: 日期对象

    Returns:
        (节气名称, 五行属性) 元组
    """
    month = date.month
    day = date.day

    # 找到当前日期对应的节气
    current_term = None
    for i, (term, term_month, term_day) in enumerate(SOLAR_TERMS):
        if month == term_month and day >= term_day:
            current_term = term
        elif month == term_month and day < term_day:
            # 如果当前月份日期小于节气日期，取上一个节气
            prev_idx = (i - 1) % len(SOLAR_TERMS)
            current_term = SOLAR_TERMS[prev_idx][0]
            break

    # 如果没找到，说明在年末，取最后一个节气
    if current_term is None:
        current_term = SOLAR_TERMS[-1][0]

    # 获取对应的五行
    wuxing = TERM_TO_WUXING.get(current_term, "土")

    return current_term, wuxing


def get_season_from_term(term: str) -> str:
    """
    根据节气获取季节

    Args:
        term: 节气名称

    Returns:
        季节名称（春/夏/秋/冬）
    """
    spring_terms = ["立春", "雨水", "惊蛰", "春分", "清明", "谷雨"]
    summer_terms = ["立夏", "小满", "芒种", "夏至", "小暑", "大暑"]
    autumn_terms = ["立秋", "处暑", "白露", "秋分", "寒露", "霜降"]
    winter_terms = ["立冬", "小雪", "大雪", "冬至", "小寒", "大寒"]

    if term in spring_terms:
        return "春"
    elif term in summer_terms:
        return "夏"
    elif term in autumn_terms:
        return "秋"
    elif term in winter_terms:
        return "冬"
    else:
        return "未知"


def get_term_description(term: str) -> str:
    """
    获取节气的描述信息

    Args:
        term: 节气名称

    Returns:
        节气描述
    """
    descriptions = {
        "立春": "春季开始，万物复苏",
        "雨水": "降雨增多，草木萌动",
        "惊蛰": "春雷乍动，蛰虫惊醒",
        "春分": "昼夜平分，春意盎然",
        "清明": "天清地明，草木繁茂",
        "谷雨": "雨生百谷，播种时节",
        "立夏": "夏季开始，万物生长",
        "小满": "麦粒渐满，雨水充沛",
        "芒种": "麦收稻种，农事繁忙",
        "夏至": "白昼最长，阳气极盛",
        "小暑": "天气炎热，雷雨频繁",
        "大暑": "一年最热，湿热交蒸",
        "立秋": "秋季开始，暑去凉来",
        "处暑": "暑气渐消，秋高气爽",
        "白露": "露凝而白，秋意渐浓",
        "秋分": "昼夜平分，秋收时节",
        "寒露": "露气寒冷，将凝结霜",
        "霜降": "天气渐冷，初霜出现",
        "立冬": "冬季开始，万物收藏",
        "小雪": "气温降低，开始降雪",
        "大雪": "降雪增多，天寒地冻",
        "冬至": "白昼最短，阴气极盛",
        "小寒": "天气寒冷，尚未大寒",
        "大寒": "一年最冷，冰天雪地",
    }
    return descriptions.get(term, "")
