# app/chat/utils.py
import json
import os
import re
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ..db import get_db


# ===================== Cache =====================

_prompt_cache: Dict[str, Tuple[str, float]] = {}  # {key: (prompt, expiry_time)}
_prompt_cache_lock = Lock()

SUGGESTED_QUESTIONS_RULES = """

【推荐追问输出协议 - 必须作为回复的最后一部分】
每次回复都必须在正文之后生成 4 个与本轮内容直接相关的后续问题，并严格使用以下格式：

---SUGGESTED_QUESTIONS---
1. 问题文本1
2. 问题文本2
3. 问题文本3
4. 问题文本4
---END_SUGGESTED_QUESTIONS---

要求：
1. 两个英文标记必须逐字、完整输出，不能省略结束标记
2. 这里的标记是“不使用分割线”规则的唯一例外
3. 每个问题 15-30 个汉字，使用疑问句，并结合本轮具体分析
4. 问题必须站在用户视角，是“用户接下来向你提问”的内容，优先使用“我、我的”
5. 禁止生成向用户采集信息的反问，例如“您是否……”“目前是否……”“请问您……”
6. 问题必须能由八字分析继续回答，不能询问用户的病史、症状、职业或生活习惯
7. 健康相关问题只能讨论命理倾向和生活管理参考，不得索取病史或提供疾病诊断
8. 标记之后不得再输出任何内容

正确示例：
1. 从命盘倾向看，我应重点关注哪些生活习惯？
2. 未来三年我的事业发展重点是什么？
3. 我的沟通方式在关系中有哪些优势？
4. 当前阶段我该如何安排学习提升计划？

错误示例：
1. 您是否长期胃部不适？
2. 目前是否有坚持运动？
3. 请问您从事什么行业？
"""

_SUGGESTED_QUESTIONS_SECTION_RE = re.compile(
    r"""
    ^[ \t]*\#{1,6}[ \t]*(?:追问|推荐追问输出协议)[ \t]*\n
    [\s\S]*?
    (?=^[ \t]*\#{1,6}[ \t]+\S|\Z)
    """,
    re.MULTILINE | re.VERBOSE,
)

_SUGGESTED_QUESTIONS_BLOCK_RE = re.compile(
    r"""
    ^[ \t]*---[ \t]*SUGGESTED_QUESTIONS[ \t]*---[ \t]*\n
    [\s\S]*?
    ^[ \t]*---[ \t]*END_SUGGESTED_QUESTIONS[ \t]*---[ \t]*\n?
    """,
    re.MULTILINE | re.VERBOSE | re.IGNORECASE,
)


def strip_suggested_questions_rules(prompt: str) -> str:
    """Remove legacy follow-up protocols before appending the canonical one."""
    without_sections = _SUGGESTED_QUESTIONS_SECTION_RE.sub("", prompt or "")
    return _SUGGESTED_QUESTIONS_BLOCK_RE.sub("", without_sections).strip()
_PROMPT_CACHE_TTL = 300  # 5 minutes default TTL


# ===================== Text Processing Utilities =====================

# 只清理形如  \n<br/>\n\n / \r\n<br />\r\n\r\n 的块；大小写不敏感
_BR_BLOCK = re.compile(r"(?:\r?\n)?<br\s*/?>\s*(?:\r?\n){2}", re.IGNORECASE)
_BR_REPLACEMENT = "\n- "

# 把所有 2+ 个连续换行压成 1 个换行：\n\n -> \n（兼容 \r\n）
_MULTI_NL = re.compile(r"(?:\r?\n){2,}")


def scrub_br_block(s: str) -> str:
    """Replace <br/>\n\n blocks with list items."""
    return _BR_BLOCK.sub(_BR_REPLACEMENT, s)


def collapse_double_newlines(s: str) -> str:
    """Collapse multiple consecutive newlines into single newline."""
    return _MULTI_NL.sub("\n", s)


def third_sub(s: str) -> str:
    """Fix malformed list items from br substitution."""
    return s.replace("\n- -", "\n-")


def append_md_rules(prompt: str) -> str:
    """Append markdown formatting rules to prompt."""
    rules = (
        "\n\n【输出格式要求-严格遵守】\n"
        "全文使用 Markdown，请注意以下格式规范：\n\n"
        "1. 标题格式：\n"
        "   - 只能使用 ###（一级标题）和 ####（二级标题）\n"
        "   - 正确写法：### 标题文字\n"
        "   - #号后面必须有一个空格\n"
        "   - 标题必须单独占一行，标题后不能直接跟内容，必须换行\n"
        "   - 标题前后各空一行（与上下内容之间有空白行）\n\n"
        "2. 错误示例（避免）：\n"
        "   ❌ ###标题\n"
        "   ❌ ### 标题后面直接接内容\n"
        "   ❌ - ### 标题（标题前不能有列表符号）\n\n"
        "3. 列表格式：\n"
        "   - 使用 `- ` 或 `1. ` 开头，每个列表项独占一行\n"
        "   - 列表项前不能有标题符号\n\n"
        "4. 其他要求：\n"
        "   - 段落之间空一行\n"
        "   - 不要使用粗体**、斜体*、引用>、分割线---（推荐追问协议的两个英文标记除外）\n"
        "   - 强调时请使用全角括号【】\n"
        "   - 避免复杂嵌套\n"
    )
    return f"{prompt}\n{rules}"


# ===================== Formatting Utilities =====================

def format_four_pillars(fp: Dict[str, List[str]]) -> str:
    """Format four pillars (年月日时) for display in prompt."""
    return (
        f"年柱: {''.join(fp['year'])}\n"
        f"月柱: {''.join(fp['month'])}\n"
        f"日柱: {''.join(fp['day'])}\n"
        f"时柱: {''.join(fp['hour'])}"
    )


def format_dayun(dy: List[Dict[str, Any]]) -> str:
    """Format ten-year dayun (大运) cycles for display in prompt."""
    lines = []
    for item in dy:
        pillar = "".join(item["pillar"])
        lines.append(f"- 起始年龄 {item['age']}，起运年 {item['start_year']}，大运 {pillar}")
    return "\n".join(lines)


def build_runtime_context(
    paipan: Optional[Dict[str, Any]] = None,
    current_dt: Optional[datetime] = None,
) -> Dict[str, str]:
    """Build deterministic chart and Shanghai-time values for prompt rendering."""
    now = current_dt or datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        now = now.astimezone(ZoneInfo("Asia/Shanghai"))

    try:
        # Keep this import lazy so prompt rendering can still start in lightweight
        # environments where optional Bazi dependencies have not been installed.
        from lunar_python import Solar

        solar = Solar.fromYmdHms(
            now.year, now.month, now.day, now.hour, now.minute, now.second
        )
        year_ganzhi = solar.getLunar().getYearInGanZhiByLiChun()
    except ImportError:
        stems = "甲乙丙丁戊己庚辛壬癸"
        branches = "子丑寅卯辰巳午未申酉戌亥"
        # Lightweight fallback. Production uses lunar_python above for the
        # exact Li Chun boundary; Feb 4 is only used when that dependency is absent.
        ganzhi_year = now.year if (now.month, now.day) >= (2, 4) else now.year - 1
        year_ganzhi = (
            stems[(ganzhi_year - 4) % 10] + branches[(ganzhi_year - 4) % 12]
        )
    chart = paipan or {}
    four_pillars = chart.get("four_pillars") or {}
    dayun = chart.get("dayun") or []

    return {
        "FOUR_PILLARS": (
            format_four_pillars(four_pillars)
            if all(four_pillars.get(key) for key in ("year", "month", "day", "hour"))
            else "以本轮用户消息中的命盘信息为准"
        ),
        "DAYUN": format_dayun(dayun) if dayun else "以本轮用户消息中的大运信息为准",
        "GENDER": str(chart.get("gender") or "以本轮用户消息中的性别信息为准"),
        "CURRENT_YEAR_GANZHI": f"{now:%Y-%m-%d}，{now.year}年，{year_ganzhi}年",
        "CURRENT_DATE": now.strftime("%Y-%m-%d"),
        "CURRENT_YEAR": str(now.year),
        "CURRENT_YEAR_GANZHI_ONLY": year_ganzhi,
        "FUTURE_THREE_YEARS": f"{now.year}年、{now.year + 1}年、{now.year + 2}年",
    }


def render_prompt_placeholders(prompt: str, context: Dict[str, str]) -> str:
    """Replace supported ``{{NAME}}`` placeholders without touching other text."""
    rendered = prompt
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


# ===================== Database Utilities =====================

@contextmanager
def db_session():
    """
    安全获取并关闭 DB session（基于 get_db 生成器）。

    Usage:
        with db_session() as db:
            db.execute(...)
    """
    db = next(get_db())
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:
            pass


def parse_value_json(v: Any) -> Dict[str, Any]:
    """
    兼容 JSON/字符串化 JSON 两种返回。

    Args:
        v: Value from database (could be dict, list, str, or None)

    Returns:
        Parsed dictionary, or empty dict if parsing fails
    """
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v if isinstance(v, dict) else {}
    if isinstance(v, str):
        try:
            data = json.loads(v)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def fetch_latest_config(db, key: str) -> Optional[Dict[str, Any]]:
    """
    读取 app_config 里最新版本的配置。

    Args:
        db: Database session
        key: Configuration key to fetch

    Returns:
        Dict with 'key', 'version', 'value_json' or None if not found
    """
    sql = """
        SELECT `cfg_key`, `version`, `value_json`
        FROM `app_config`
        WHERE `cfg_key` = :key
        ORDER BY `version` DESC
        LIMIT 1
    """
    row = db.execute(text(sql), {"key": key}).mappings().first()
    if not row:
        return None
    return {
        "key": row["cfg_key"],
        "version": row["version"],
        "value_json": parse_value_json(row["value_json"]),
    }


def load_system_prompt_from_db(ttl: int = _PROMPT_CACHE_TTL) -> str:
    """
    从数据库加载系统提示词（带缓存）。

    优先读取 system_prompt，若不存在回退 rprompt。
    结构期望：value_json = { "content": "......", "notes": "..." }

    Args:
        ttl: Cache time-to-live in seconds (default: 300)

    Returns:
        System prompt content, or empty string if not found
    """
    cache_key = "system_prompt"
    now = time.time()

    with _prompt_cache_lock:
        if cache_key in _prompt_cache:
            content, expiry = _prompt_cache[cache_key]
            if now < expiry:
                return content

    # Cache miss or expired, load from DB
    with db_session() as db:
        cfg = fetch_latest_config(db, "system_prompt")
        if not cfg:
            cfg = fetch_latest_config(db, "rprompt")
        if not cfg:
            return ""
        content = (cfg["value_json"] or {}).get("content") or ""

        # Update cache
        with _prompt_cache_lock:
            _prompt_cache[cache_key] = (content, now + ttl)

        return content


def load_report_system_prompt_from_db(ttl: int = _PROMPT_CACHE_TTL) -> str:
    """
    从数据库加载报告页专用提示词（带缓存）。

    读取 report_system_prompt；不存在则回退至通用 system_prompt。
    """
    cache_key = "report_system_prompt"
    now = time.time()

    with _prompt_cache_lock:
        if cache_key in _prompt_cache:
            content, expiry = _prompt_cache[cache_key]
            if now < expiry:
                return content

    with db_session() as db:
        cfg = fetch_latest_config(db, "report_system_prompt")
        if not cfg:
            # fallback to general system_prompt
            return load_system_prompt_from_db(ttl)
        content = (cfg["value_json"] or {}).get("content") or ""

        with _prompt_cache_lock:
            _prompt_cache[cache_key] = (content, now + ttl)

        return content


def load_liuyao_system_prompt_from_db(ttl: int = _PROMPT_CACHE_TTL) -> str:
    """
    从数据库加载六爻对话专用提示词（带缓存）。

    读取 liuyao_system_prompt；不存在则返回空串（由调用方使用模块内默认 prompt）。
    """
    cache_key = "liuyao_system_prompt"
    now = time.time()

    with _prompt_cache_lock:
        if cache_key in _prompt_cache:
            content, expiry = _prompt_cache[cache_key]
            if now < expiry:
                return content

    with db_session() as db:
        cfg = fetch_latest_config(db, "liuyao_system_prompt")
        if not cfg:
            return ""
        content = (cfg["value_json"] or {}).get("content") or ""

        with _prompt_cache_lock:
            _prompt_cache[cache_key] = (content, now + ttl)

        return content


def clear_prompt_cache(key: Optional[str] = None) -> None:
    """Clear one prompt cache entry, or all prompt cache entries."""
    with _prompt_cache_lock:
        if key:
            _prompt_cache.pop(key, None)
        else:
            _prompt_cache.clear()


# ===================== Timing Utilities =====================

@contextmanager
def timer(section: str, spans: Dict[str, float]):
    """
    计时上下文管理器。

    Usage:
        spans = {}
        with timer("db_query", spans):
            # do work
        print(spans["db_query"])  # elapsed time in seconds

    Args:
        section: Key name for the span
        spans: Dictionary to store timing results
    """
    s = time.perf_counter()
    try:
        yield
    finally:
        spans[section] = time.perf_counter() - s


def now_ms() -> int:
    """Get current time in milliseconds."""
    return int(time.time() * 1000)


def to_ms(spans: Dict[str, float]) -> Dict[str, int]:
    """Convert seconds to milliseconds."""
    return {k: int(v * 1000) for k, v in spans.items()}


# ===================== Incremental Text Processing =====================

class IncrementalNormalizer:
    """
    Incrementally normalize markdown text to avoid O(n²) complexity.

    Instead of normalizing the entire accumulated text on each token,
    this class batches normalization and only processes dirty regions.
    """

    def __init__(self, normalize_interval: int = 50, apply_content_filter: bool = True):
        """
        Args:
            normalize_interval: Normalize every N tokens (default: 50)
            apply_content_filter: Whether to apply sensitive word filtering (default: True)
        """
        from .markdown_utils import normalize_markdown

        self._normalize_markdown = normalize_markdown
        self._normalize_interval = normalize_interval
        self._apply_content_filter = apply_content_filter
        self._raw_chunks: List[str] = []
        self._token_count = 0
        self._last_normalized: str = ""

    def append(self, delta: str) -> Optional[str]:
        """
        Append a delta and return normalized text if it's time to normalize.

        Args:
            delta: New text chunk

        Returns:
            Normalized full text if at interval, otherwise None
        """
        self._raw_chunks.append(delta)
        self._token_count += 1

        # Only normalize every N tokens
        if self._token_count % self._normalize_interval == 0:
            return self._normalize()

        return None

    def finalize(self) -> str:
        """
        Finalize and return the fully normalized text.

        Returns:
            Completely normalized text
        """
        return self._normalize()

    def _normalize(self) -> str:
        """Normalize all accumulated chunks."""
        raw = "".join(self._raw_chunks)
        normalized = self._normalize_markdown(raw)
        # Apply additional cleanup
        normalized = scrub_br_block(normalized)
        normalized = collapse_double_newlines(normalized)
        normalized = third_sub(normalized)
        # Apply sensitive word filtering
        if self._apply_content_filter:
            try:
                from .content_filter import apply_content_filters
                pre_filter = normalized
                with db_session() as db:
                    filtered = apply_content_filters(normalized, db)
                # Safety: if filtering blanked >50% of the text, skip it
                if filtered and len(filtered.strip()) >= len(pre_filter.strip()) * 0.5:
                    normalized = filtered
                    # 修复敏感词过滤后可能被拆分的标题
                    import re
                    normalized = re.sub(
                        r'^(#{1,6}\s+.+?)\n([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{1,5})\n',
                        r'\1\2\n',
                        normalized,
                        flags=re.MULTILINE
                    )
                    normalized = self._normalize_markdown(normalized)
            except Exception:
                # 过滤失败不影响主流程
                pass
        self._last_normalized = normalized
        return normalized


# ===================== Prompt Building =====================

def build_full_system_prompt(
    base_prompt: str,
    kb_passages: List[str],
    paipan: Optional[Dict[str, Any]] = None,
    current_dt: Optional[datetime] = None,
    include_suggested_questions: bool = True,
) -> str:
    """
    由 DB 加载的 base_prompt，附加格式规则与 KB 片段。
    Fill chart/time placeholders and append the canonical runtime time anchor.

    Args:
        base_prompt: Base system prompt from database
        kb_passages: Retrieved knowledge base passages

    Returns:
        Fully rendered system prompt containing the current chart and time anchor
    """
    # The admin-managed prompt may still contain an older follow-up section.
    # Remove it so the model receives exactly one canonical protocol, placed
    # after every other formatting rule.
    runtime = build_runtime_context(paipan, current_dt)
    composed = render_prompt_placeholders(
        strip_suggested_questions_rules(base_prompt or ""), runtime
    )
    composed += (
        "\n\n【当前时间锚点 - 涉及阶段分析时必须遵守】\n"
        f"当前公历日期：{runtime['CURRENT_DATE']}\n"
        f"当前公历年份：{runtime['CURRENT_YEAR']}年\n"
        f"当前流年干支：{runtime['CURRENT_YEAR_GANZHI_ONLY']}\n"
        f"未来三年固定指：{runtime['FUTURE_THREE_YEARS']}\n"
        "凡出现“今年”“当前”“未来三年”“近三年”，均以上述日期为起点。\n"
        "除非用户明确要求回顾过去，否则不得把当前年份以前的年份列入未来阶段。\n"
        "分析阶段变化时，先核对对应年份的大运与流年，再给出判断。"
    )
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"
    # Keep the single machine-readable follow-up protocol last so that later
    # formatting instructions cannot accidentally override it.
    # Skip it for one-shot reports (the report page has its own CTA flow).
    if include_suggested_questions:
        return f"{append_md_rules(composed)}{SUGGESTED_QUESTIONS_RULES}"
    return append_md_rules(composed)
