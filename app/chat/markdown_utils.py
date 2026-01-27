# app/chat/markdown_utils.py
import re
from typing import List, Tuple

# 保护代码块/行内代码
_RE_FENCED = re.compile(r"```.*?```", re.DOTALL)
_RE_INLINE = re.compile(r"`[^`\n]*`")

# 能开新块的结构行
_RE_STRUCTURAL = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s|>|\||```|</?)")

_TAIL_TOKENS = {"点", "析", "览", ")", "）", "]", "】", "?", "？", "!", "！", ":", "：", "—"}

# === 新增：确保标题块前后都有空行（硬性切断上一段） ===
_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+\S.*$", re.M)

def _extract_placeholders(s: str, regex: re.Pattern, tag: str) -> Tuple[str, list[str]]:
    store: List[str] = []
    def _repl(m):
        store.append(m.group(0))
        return f"@@{tag}{len(store)-1}@@"
    return regex.sub(_repl, s), store

def _restore_placeholders(s: str, store: list[str], tag: str) -> str:
    for i, txt in enumerate(store):
        s = s.replace(f"@@{tag}{i}@@", txt)
    return s

def _paren_balance(text: str) -> int:
    pairs = {")":"(", "）":"（", "]":"[", "】":"【"}
    lefts = set(pairs.values())
    stack: List[str] = []
    for ch in text:
        if ch in lefts:
            stack.append(ch)
        elif ch in pairs:
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
            else:
                return -1
    return len(stack)

def _ensure_heading_blocks(s: str) -> str:
    """
    把所有标题行强制变成一个"独立块"：
    - 标题行前：若不是文首且前一行不是空行，补一个空行
    - 标题行后：若下一行不是空行，补一个空行（但不重复添加）
    这样 ReactMarkdown/marked 等解析器一定会把它当作标题，而不是普通段落里的文字。
    """
    lines = s.split("\n")
    n = len(lines)
    i = 0
    out: list[str] = []
    while i < n:
        ln = lines[i]
        if _HEADING_LINE.match(ln):
            # 确保前一行空行
            if out and out[-1].strip() != "":
                out.append("")  # 插入空行
            # 检查下一行是否是标题的尾部（1-5个中文字符的短行）
            nxt = lines[i+1] if i+1 < n else None
            if nxt is not None:
                nxt_stripped = nxt.strip()
                # 如果下一行是1-5个中文字符且不是结构行，合并到标题
                if (len(nxt_stripped) <= 5 and
                    nxt_stripped and
                    not _RE_STRUCTURAL.match(nxt) and
                    all('\u4e00' <= c <= '\u9fff' or c in '，。！？、；：""''（）【】' for c in nxt_stripped)):
                    out.append(ln.rstrip() + nxt_stripped)
                    i += 2
                    # 检查合并后的下一行
                    nxt2 = lines[i] if i < n else None
                    if nxt2 is not None and nxt2.strip() != "":
                        out.append("")
                    continue
            out.append(ln.rstrip())
            # 确保标题后有一个空行（不重复添加）
            nxt = lines[i+1] if i+1 < n else None
            # 只有当下一行不是空行时才添加空行
            if nxt is not None and nxt.strip() != "":
                out.append("")
            # 注意：不再在文档末尾添加多余空行
            i += 1
            continue
        out.append(ln)
        i += 1
    # 折叠 2 个以上的连续空行为单个空行
    # 这样可以避免标题后出现多个空行导致 markdown 解析问题
    s2 = "\n".join(out)
    # 不要折叠标题后的空行，保持标题与内容之间的分隔
    # 只折叠非标题区域的多个空行
    s2 = re.sub(r"\n{3,}", "\n\n", s2)
    return s2

# 行首的 ###/####... 去掉（保留原缩进与换行）
_HEADING_HASHES = re.compile(r"(?m)^(\s*)#{1,6}\s+")
def _strip_heading_hashes(s: str) -> str:
    return _HEADING_HASHES.sub(r"\1", s)

# 冒号后紧跟列表时，确保有一个空行：把 "：\n- " / ":\n- " 变成 "：\n\n- "
_COLON_LIST = re.compile(r"([：:])\s*(?:\r?\n)(?=\s*-\s+\S)")
def _ensure_blankline_before_list_after_colon(s: str) -> str:
    return _COLON_LIST.sub(r"\1\n\n", s)


# 标题后第一个空格处添加换行（如果空格后跟中文内容且不是行尾）
# 匹配：### 八字命盘总览 年柱：... -> ### 八字命盘总览\n年柱：...
# 修复：避免在标题行末尾单独产生换行
_HEADING_SPACE_CONTENT = re.compile(r'^(#{1,6}\s+[\u4e00-\u9fff]+)\s+(?=[\u4e00-\u9fff].)', re.MULTILINE)

# 标题后直接跟着关键词（无空格）的情况
# 匹配：### 出生结构个人画像总览年柱：乙巳 -> ### 出生结构个人画像总览\n\n年柱：乙巳
_HEADING_KEYWORD_SPLIT = re.compile(
    r'^(#{1,6}\s+[^\n]+?)(年柱|月柱|日柱|时柱|性别|起运|大运|流年|命主|日主)([：:].*)$',
    re.MULTILINE
)

def _split_heading_content(s: str) -> str:
    """在标题后的第一个空格处添加换行（如果空格后跟中文且后面还有内容）"""
    # 先替换，然后清理可能产生的标题后空行
    result = _HEADING_SPACE_CONTENT.sub(r'\1\n', s)
    # 移除标题行后立即出现的空行（避免单独的换行导致标题被拆分）
    result = re.sub(r'^(#{1,6}[^\n]*)\n\s*\n', r'\1\n', result, flags=re.MULTILINE)
    return result


def _split_heading_keyword(s: str) -> str:
    """
    处理标题后直接跟着关键词（无空格）的情况。
    例如：### 出生结构个人画像总览年柱：乙巳 -> ### 出生结构个人画像总览\n\n年柱：乙巳
    """
    return _HEADING_KEYWORD_SPLIT.sub(r'\1\n\n\2\3', s)


def normalize_markdown(md: str) -> str:
    """
    - 统一换行/去零宽
    - 修复被拆开的标题（含“孤字尾行”“右括号独行”“括号未配平”）
    - 折叠多余空行
    """
    if not md:
        return md

    s = md.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub("[\u200b\u200c\u200d\ufeff]", "", s)

    # 保护代码
    s, fenced = _extract_placeholders(s, _RE_FENCED, "F")
    s, inline  = _extract_placeholders(s, _RE_INLINE,  "I")

    lines = s.split("\n")
    out: List[str] = []
    i = 0
    # 排除模式：看起来像独立内容行而非标题碎片
    # 如：年柱：、月柱：、日柱：、时柱：、起运：、大运：等
    _EXCLUDE_PREFIXES = (
        '年柱', '月柱', '日柱', '时柱', '起运', '大运', '流年',
        '命主', '日主', '性别', '格局', '喜用', '忌神',
        '财星', '官星', '印星', '食伤', '比劫',
        '事业', '财运', '感情', '婚姻', '健康',
    )
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*#{1,6}\s+\S", line):
            parts = [line.strip()]
            j = i + 1
            need_balance = _paren_balance(parts[0]) > 0
            seen_blank = False  # 是否已经遇到空行
            while j < len(lines):
                nxt = lines[j]
                stripped = nxt.strip()
                if stripped == "":
                    seen_blank = True  # 标记遇到空行
                    j += 1
                    continue
                # 如果已经遇到空行，且不需要平衡括号，则停止合并
                if seen_blank and not need_balance:
                    break
                if need_balance:
                    parts.append(stripped)
                    need_balance = _paren_balance(" ".join(parts)) > 0
                    j += 1
                    continue
                if _RE_STRUCTURAL.match(nxt):
                    break
                # 检查是否以排除前缀开头（如"年柱：乙巳..."），如果是则不合并
                if stripped.startswith(_EXCLUDE_PREFIXES):
                    break
                if len(stripped) <= 24 or stripped in _TAIL_TOKENS:
                    parts.append(stripped)
                    need_balance = _paren_balance(" ".join(parts)) > 0
                    j += 1
                    continue
                break
            merged = " ".join(parts)
            out.append(merged)
            out.append("")
            i = j
            continue
        out.append(line)
        i += 1

    s = "\n".join(out)
    s = re.sub(r"\n{3,}", "\n\n", s)

    # 清理遗留的 <br/> 标签（可能导致显示问题）
    s = re.sub(r"<br\s*/?>", "", s)

    # 这里替换  \n<br/>\n\n 以及常见等价写法为一个空格
    s = re.sub(r"(?:\r?\n)?<br\s*/?>\s*\r?\n\r?\n", " ", s)

    # 还原代码
    s = _restore_placeholders(s, inline,  "I")
    s = _restore_placeholders(s, fenced, "F")

    # === 处理标题后直接跟着关键词的情况 ===
    s = _split_heading_keyword(s)

    # === 新增：标题块强制换行 ===
    s = _ensure_heading_blocks(s)

    return s.strip()
