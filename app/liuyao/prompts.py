"""
六爻对话相关的 prompt 构造与常量。
"""
from __future__ import annotations

from typing import Iterable, List

from app.models.liuyao import LiuyaoHexagram


GENDER_DISPLAY = {"male": "男", "female": "女", "unknown": "未知"}


def _moving_lines_text(hexagram: LiuyaoHexagram) -> str:
    """从 hexagram.lines 中提取动爻描述。"""
    lines_obj = hexagram.lines or {}
    raw_lines = lines_obj.get("lines") if isinstance(lines_obj, dict) else []
    moving = [i + 1 for i, ln in enumerate(raw_lines or []) if ln.get("is_dong")]
    if not moving:
        return "无动爻"
    return "、".join(f"第{n}爻" for n in moving)


def _format_ganzhi(hexagram: LiuyaoHexagram) -> str:
    gz = hexagram.ganzhi or {}
    if not isinstance(gz, dict):
        return ""
    parts = [gz.get("year"), gz.get("month"), gz.get("day"), gz.get("hour")]
    return " ".join(p for p in parts if p)


def build_hexagram_context(hexagram: LiuyaoHexagram) -> str:
    """
    把卦象结构化信息压成一段固定上下文，给 system prompt 与开场用户消息共用。
    """
    gender = GENDER_DISPLAY.get(hexagram.gender or "", "未知")
    ganzhi = _format_ganzhi(hexagram)
    jiqi = ""
    if isinstance(hexagram.jiqi, dict):
        jiqi = hexagram.jiqi.get("current") or ""

    segments = [
        f"- 所问之事：{hexagram.question}",
        f"- 性别：{gender}",
        f"- 本卦：{hexagram.main_gua or '（未知）'}",
        f"- 变卦：{hexagram.change_gua or '无变卦'}",
        f"- 动爻：{_moving_lines_text(hexagram)}",
    ]
    if hexagram.shi_yao:
        segments.append(f"- 世爻：第{hexagram.shi_yao}爻")
    if hexagram.ying_yao:
        segments.append(f"- 应爻：第{hexagram.ying_yao}爻")
    if ganzhi:
        segments.append(f"- 干支：{ganzhi}")
    if jiqi:
        segments.append(f"- 节气：{jiqi}")
    if hexagram.gua_shen:
        segments.append(f"- 卦身：{hexagram.gua_shen}")
    if hexagram.shensha:
        segments.append(f"- 神煞：{hexagram.shensha}")
    if hexagram.lunar_date:
        segments.append(f"- 农历：{hexagram.lunar_date}")
    return "\n".join(segments)


LIUYAO_BASE_SYSTEM_PROMPT = """你是一位精通《易经》六爻的分析师，同时具备心理洞察与现实决策能力。

你的目标不是预测未来，而是帮助用户看清局势、识别问题、做出更好的选择。

风格要求：
- 理性、克制，略带锋芒，不神叨、不空话、不煽情。
- 回答要基于用户卦象（本卦、变卦、动爻、世应、六亲、六兽、干支、节气）给出具体判断。
- 结论要落地、可执行；避免"一定会""命中注定"这类绝对判断。
- 不要每次都从头复述卦象信息，用户追问时直接针对问题作答，必要时引用关键爻位。
"""


def build_system_prompt(hexagram: LiuyaoHexagram, kb_passages: Iterable[str]) -> str:
    """构建六爻多轮对话的 system prompt。"""
    kb_list = [p for p in (kb_passages or []) if p]
    kb_block = ""
    if kb_list:
        joined = "\n\n".join(kb_list[:5])
        kb_block = f"\n\n【知识库摘录】\n{joined}\n\n请优先结合以上知识库条目进行判断。"

    context = build_hexagram_context(hexagram)

    return (
        f"{LIUYAO_BASE_SYSTEM_PROMPT}"
        f"\n\n【本次卦象】\n{context}"
        f"{kb_block}"
        "\n\n【输出规范】\n"
        "- 仅允许使用 `###` 与 `####` 作为 Markdown 标题。\n"
        "- 段落之间用单行空行分隔，不使用粗体、斜体、引用块、分割线。\n"
        "- 列表使用 `-` 起始。\n"
    )


def build_opening_user_message(hexagram: LiuyaoHexagram) -> str:
    """
    /chat/start 的开场 user 消息：要求 AI 按固定结构做第一次解卦。
    """
    context = build_hexagram_context(hexagram)
    return (
        "请基于以下卦象做第一次解读：\n\n"
        f"{context}\n\n"
        "请按如下结构输出：\n\n"
        "### 1. 你真正面对的问题\n"
        "一句话点出用户背后的真正焦虑或不确定。\n\n"
        f"### 2. 当前状态｜{hexagram.main_gua or '本卦'}\n"
        "结合本卦、世应与用神说明当前局面。\n\n"
        f"### 3. 发展趋势｜{hexagram.change_gua or '静卦'}\n"
        "结合变卦（若有）或静卦态势说明走向。\n\n"
        "### 4. 核心矛盾\n"
        "指出 1-2 个关键矛盾。\n\n"
        "### 5. 行动建议\n"
        "给出可执行的、现实的建议。\n\n"
        "### 6. 一句话提醒\n"
        "给一句让人停下来想一秒的收束。"
    )


CHARACTER_PROMPT = (
    "请基于当前卦象，专门分析与此问相关的人物画像。要求：\n"
    "1. 体型外貌：身高、体形、脸型、五官倾向（结合五行/六亲/卦气推断）。\n"
    "2. 气质神态：给人的第一印象、声音、眼神。\n"
    "3. 性格倾向：主导性格、处世方式、情绪底色。\n"
    "4. 行为动作：近期可能的行动轨迹、典型行为姿态。\n\n"
    "要求：\n"
    "- 从世应、用神、动爻、六亲、六兽、五行多角度交叉印证。\n"
    "- 写出画面感，不空泛，不写成通用星座描述。\n"
    "- 若人物信息在卦象中不明显，请明确说明不确定点，不要硬编。"
)


TIMING_PROMPT = (
    "请基于当前卦象，专门分析应期（事情发生或落定的时间节点）。要求：\n"
    "1. 短期应期：最可能的日、时（精确到 1-7 天内）。\n"
    "2. 中期应期：月、节气、旬空解除的时间。\n"
    "3. 长期应期：年、流年对应（如有必要）。\n"
    "4. 关键节点判断依据：动爻、合冲、空亡、月破、墓库、进退神等。\n\n"
    "要求：\n"
    "- 先给出具体时间窗口（例如『农历三月初七前后』『寅日寅时』），再解释取象逻辑。\n"
    "- 若有多个可能的应期，按概率高低排序并说明差异。\n"
    "- 不用『命中注定』『一定会』这类绝对表达。"
)


QUICK_PROMPTS: dict[str, str] = {
    "character": CHARACTER_PROMPT,
    "timing": TIMING_PROMPT,
}


QUICK_LABELS: dict[str, str] = {
    "character": "人物画像分析",
    "timing": "应期分析",
}
