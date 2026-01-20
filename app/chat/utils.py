# app/chat/utils.py
import json
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock

from sqlalchemy import text

from ..db import get_db


# ===================== Cache =====================

_prompt_cache: Dict[str, Tuple[str, float]] = {}  # {key: (prompt, expiry_time)}
_prompt_cache_lock = Lock()
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
        "   - 不要使用粗体**、斜体*、引用>、分割线---\n"
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


def clear_prompt_cache() -> None:
    """Clear the system prompt cache."""
    with _prompt_cache_lock:
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

    def __init__(self, normalize_interval: int = 50):
        """
        Args:
            normalize_interval: Normalize every N tokens (default: 50)
        """
        from .markdown_utils import normalize_markdown

        self._normalize_markdown = normalize_markdown
        self._normalize_interval = normalize_interval
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
        self._last_normalized = normalized
        return normalized


# ===================== Prompt Building =====================

def build_full_system_prompt(
    base_prompt: str,
    mingpan: Dict[str, Any],
    kb_passages: List[str]
) -> str:
    """
    由 DB 加载的 base_prompt，填充 {FOUR_PILLARS}/{DAYUN}，并附加格式规则与 KB 片段。

    Args:
        base_prompt: Base system prompt from database
        mingpan: Bazi calculation result with four_pillars and dayun
        kb_passages: Retrieved knowledge base passages

    Returns:
        Complete system prompt ready for AI
    """
    fp_text = format_four_pillars(mingpan["four_pillars"])
    dy_text = format_dayun(mingpan["dayun"])
    gender = mingpan.get("gender", "")
    composed = (base_prompt or "")
    composed = composed.replace("{{GENDER}}", gender).replace("{{FOUR_PILLARS}}", fp_text).replace("{{DAYUN}}", dy_text)
    if kb_passages:
        kb_block = "\n\n".join(kb_passages[:3])
        composed += f"\n\n【知识库摘录】\n{kb_block}\n\n请严格基于以上材料与排盘信息回答。"
    return append_md_rules(composed)
