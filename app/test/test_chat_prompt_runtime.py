from datetime import datetime
from zoneinfo import ZoneInfo

from app.chat.utils import build_full_system_prompt


SAMPLE_PAIPAN = {
    "gender": "女",
    "four_pillars": {
        "year": ["癸", "酉"],
        "month": ["乙", "卯"],
        "day": ["己", "丑"],
        "hour": ["丁", "卯"],
    },
    "dayun": [
        {"age": 8, "start_year": 2025, "pillar": ["辛", "亥"]},
    ],
}


def test_prompt_renders_chart_and_current_time_placeholders():
    base_prompt = (
        "八字：{{FOUR_PILLARS}}\n"
        "大运：{{DAYUN}}\n"
        "性别：{{GENDER}}\n"
        "当前时间：{{CURRENT_YEAR_GANZHI}}"
    )
    now = datetime(2026, 7, 28, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    prompt = build_full_system_prompt(
        base_prompt, [], paipan=SAMPLE_PAIPAN, current_dt=now
    )

    assert "{{" not in prompt
    assert "年柱: 癸酉" in prompt
    assert "起运年 2025，大运 辛亥" in prompt
    assert "性别：女" in prompt
    assert "当前公历日期：2026-07-28" in prompt
    assert "当前流年干支：丙午" in prompt
    assert "未来三年固定指：2026年、2027年、2028年" in prompt


def test_prompt_forbids_past_year_in_future_window():
    now = datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

    prompt = build_full_system_prompt("角色说明", [], current_dt=now)

    assert "除非用户明确要求回顾过去" in prompt
    assert "不得把当前年份以前的年份列入未来阶段" in prompt
