import httpx, re
from typing import List
from ..config import settings
from ..schemas import Msg

SAFE_PAT = re.compile(r"(算命|占卜|风水|改命|保佑|灵验|处方|诊断|买卖股票|内幕|政治|仇恨)")

def guard_or_none(messages: List[Msg]) -> str | None:
    last = next((m.content for m in reversed(messages) if m.role=="user"), "")
    if SAFE_PAT.search(last):
        return "这个话题我不方便直接回答。我们可以聊聊提升心态、时间管理或日常规划的小建议哦～（仅供参考）"
    return None

async def call_ai(messages: List[Msg]) -> str:
    """可接入混元/其它；为空时用本地模板回复"""
    guard = guard_or_none(messages)
    if guard: return guard

    if not settings.AI_API_URL or not settings.AI_API_KEY:
        last = next((m.content for m in reversed(messages) if m.role=="user"), "")
        return f"我理解你的问题是「{last}」。给你三个角度：\n1) 明确目标\n2) 拆解步骤\n3) 设定下一个可执行动作。\n（仅供参考）"

    # 示例调用（按你的供应商文档调整）
    try:
        headers = {"Authorization": f"Bearer {settings.AI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "your-model", "messages": [m.model_dump() for m in messages], "temperature": 0.7}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(settings.AI_API_URL, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        last = next((m.content for m in reversed(messages) if m.role=="user"), "")
        return f"（已切换为简洁回答）关于「{last}」，建议先聚焦最重要的一步开始，保持节奏即可。"
