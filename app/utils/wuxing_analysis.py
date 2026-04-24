# app/utils/wuxing_analysis.py
"""
五行分析工具
基于用户八字数据分析五行属性和性格特征
"""
from typing import Dict, List, Optional
import json


# 五行生克关系
WUXING_SHENG = {
    "木": "火",  # 木生火
    "火": "土",  # 火生土
    "土": "金",  # 土生金
    "金": "水",  # 金生水
    "水": "木",  # 水生木
}

WUXING_KE = {
    "木": "土",  # 木克土
    "火": "金",  # 火克金
    "土": "水",  # 土克水
    "金": "木",  # 金克木
    "水": "火",  # 水克火
}

# 天干五行属性
TIANGAN_WUXING = {
    "甲": "木", "乙": "木",
    "丙": "火", "丁": "火",
    "戊": "土", "己": "土",
    "庚": "金", "辛": "金",
    "壬": "水", "癸": "水",
}

# 地支五行属性
DIZHI_WUXING = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木",
    "辰": "土", "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土", "亥": "水",
}

# 五行性格特征
WUXING_TRAITS = {
    "木": {
        "positive": ["仁慈", "正直", "进取", "有条理", "善于规划"],
        "negative": ["固执", "缺乏变通", "过于理想化"],
        "emotion_tendency": "容易焦虑和紧张，需要放松和接纳",
        "advice": "多接触自然，培养灵活性，学会顺其自然"
    },
    "火": {
        "positive": ["热情", "积极", "有礼", "善于表达", "富有创造力"],
        "negative": ["急躁", "冲动", "情绪化"],
        "emotion_tendency": "情绪起伏大，容易激动，需要冷静和沉淀",
        "advice": "学会控制情绪，培养耐心，多做冥想练习"
    },
    "土": {
        "positive": ["稳重", "诚信", "包容", "务实", "有责任感"],
        "negative": ["保守", "迟缓", "过于谨慎"],
        "emotion_tendency": "情绪稳定但容易压抑，需要表达和释放",
        "advice": "勇于表达内心感受，适度冒险，保持开放心态"
    },
    "金": {
        "positive": ["果断", "坚毅", "有原则", "理性", "执行力强"],
        "negative": ["刚硬", "缺乏柔性", "过于严格"],
        "emotion_tendency": "理性压抑感性，需要柔软和共情",
        "advice": "培养同理心，接纳脆弱，学会示弱和求助"
    },
    "水": {
        "positive": ["智慧", "灵活", "善于适应", "富有想象力"],
        "negative": ["多疑", "摇摆不定", "缺乏主见"],
        "emotion_tendency": "情绪流动性强，容易受环境影响，需要稳定和坚持",
        "advice": "建立稳定的生活节奏，培养意志力，坚持长期目标"
    }
}


def analyze_bazi_wuxing(bazi_data: Dict) -> Dict[str, any]:
    """
    分析八字中的五行分布

    Args:
        bazi_data: 八字数据，包含四柱信息

    Returns:
        五行分析结果
    """
    wuxing_count = {"木": 0, "火": 0, "土": 0, "金": 0, "水": 0}

    # 从八字数据中提取天干地支
    # 假设 bazi_data 格式: {"year": "甲子", "month": "乙丑", "day": "丙寅", "hour": "丁卯"}
    pillars = []
    for key in ["year", "month", "day", "hour"]:
        if key in bazi_data and bazi_data[key]:
            pillar = bazi_data[key]
            if len(pillar) >= 2:
                pillars.append((pillar[0], pillar[1]))  # (天干, 地支)

    # 统计五行
    for tiangan, dizhi in pillars:
        if tiangan in TIANGAN_WUXING:
            wuxing_count[TIANGAN_WUXING[tiangan]] += 1
        if dizhi in DIZHI_WUXING:
            wuxing_count[DIZHI_WUXING[dizhi]] += 1

    # 找出最强和最弱的五行
    sorted_wuxing = sorted(wuxing_count.items(), key=lambda x: x[1], reverse=True)
    strongest = sorted_wuxing[0][0] if sorted_wuxing[0][1] > 0 else None
    weakest = sorted_wuxing[-1][0] if sorted_wuxing[-1][1] < sorted_wuxing[0][1] else None

    return {
        "wuxing_count": wuxing_count,
        "strongest": strongest,
        "weakest": weakest,
        "balance_score": calculate_balance_score(wuxing_count)
    }


def calculate_balance_score(wuxing_count: Dict[str, int]) -> float:
    """
    计算五行平衡度（0-100分）

    Args:
        wuxing_count: 五行数量统计

    Returns:
        平衡度分数
    """
    values = list(wuxing_count.values())
    if not values or sum(values) == 0:
        return 0.0

    avg = sum(values) / len(values)
    variance = sum((x - avg) ** 2 for x in values) / len(values)
    std_dev = variance ** 0.5

    # 标准差越小，平衡度越高
    # 假设标准差为0时得100分，标准差为2时得0分
    balance_score = max(0, 100 - (std_dev / 2) * 100)
    return round(balance_score, 2)


def get_character_profile(wuxing_element: str) -> Dict[str, any]:
    """
    根据主导五行获取性格档案

    Args:
        wuxing_element: 五行属性（木/火/土/金/水）

    Returns:
        性格档案
    """
    if wuxing_element not in WUXING_TRAITS:
        return {}

    traits = WUXING_TRAITS[wuxing_element]
    return {
        "element": wuxing_element,
        "positive_traits": traits["positive"],
        "negative_traits": traits["negative"],
        "emotion_tendency": traits["emotion_tendency"],
        "advice": traits["advice"]
    }


def get_emotion_guidance(user_wuxing: str, current_emotion_score: int) -> str:
    """
    根据用户五行属性和当前情绪评分，提供情绪引导建议

    Args:
        user_wuxing: 用户主导五行
        current_emotion_score: 当前情绪评分 (1-10)

    Returns:
        情绪引导文本
    """
    if user_wuxing not in WUXING_TRAITS:
        return "请保持觉察，关注当下的感受。"

    traits = WUXING_TRAITS[user_wuxing]

    if current_emotion_score <= 3:
        # 低分情绪
        return f"你的{user_wuxing}属性{traits['emotion_tendency']}。{traits['advice']}。记住，情绪如同天气，终会过去。"
    elif current_emotion_score <= 6:
        # 中等情绪
        return f"作为{user_wuxing}属性的你，{traits['emotion_tendency']}。试着觉察此刻的感受，不评判，只是看见。"
    else:
        # 高分情绪
        return f"很高兴看到你的积极状态！{user_wuxing}属性让你{', '.join(traits['positive'][:3])}。继续保持这份能量。"


def extract_bazi_from_profile(profile_data: Optional[str]) -> Optional[Dict]:
    """
    从用户档案中提取八字数据

    Args:
        profile_data: 用户档案JSON字符串

    Returns:
        八字数据字典，如果无法提取则返回None
    """
    if not profile_data:
        return None

    try:
        data = json.loads(profile_data) if isinstance(profile_data, str) else profile_data
        # 假设档案中包含 bazi 字段
        if "bazi" in data:
            return data["bazi"]
        return None
    except (json.JSONDecodeError, TypeError):
        return None
