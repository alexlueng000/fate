# app/chat/markdown_utils.py
import re
from typing import List, Tuple

# 保护代码块/行内代码
_RE_FENCED = re.compile(r"```.*?```", re.DOTALL)
_RE_INLINE = re.compile(r"`[^`\n]*`")

# 能开新块的结构行
_RE_STRUCTURAL = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s|>|\||```|</?)")

_TAIL_TOKENS = {"点", "析", "览", ")", "）", "]", "】", "?", "？", "!", "！", ":", "：", "—"}

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
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*#{1,6}\s+\S", line):
            parts = [line.strip()]
            j = i + 1
            need_balance = _paren_balance(parts[0]) > 0
            while j < len(lines):
                nxt = lines[j]
                stripped = nxt.strip()
                if stripped == "":
                    j += 1
                    continue
                if need_balance:
                    parts.append(stripped)
                    need_balance = _paren_balance(" ".join(parts)) > 0
                    j += 1
                    continue
                if _RE_STRUCTURAL.match(nxt):
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

    # 还原代码
    s = _restore_placeholders(s, inline,  "I")
    s = _restore_placeholders(s, fenced, "F")

    return s.strip()
