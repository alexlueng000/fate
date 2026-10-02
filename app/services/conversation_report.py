"""Read a complete report from persisted messages, without another model call.

The first complete report remains the source as follow-up messages are appended.
No synthetic summary or inferred user facts are stored in this view.
"""
import re

TOPIC_TITLES = (
    {"核心观察", "核心判断"},
    {"分析依据"},
    {"现实建议", "行动建议"},
)
PERSONAL_TITLES = ["个人画像", "性格特点", "做事方式", "人际与感情", "行动建议", "三年关键节点", "免责声明"]


def report_sections(content: str) -> list[dict]:
    # Protocol questions are rendered separately, never inside the advice body.
    content = re.split(r"---\s*SUGGESTED_QUESTIONS\s*---", content, maxsplit=1)[0]
    headings = []
    fence = None
    offset = 0
    for line in content.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            match = re.match(r"^###\s+(.+?)\s*#*\s*$", line)
            if match:
                # The legacy Markdown normalizer appends a WORD JOINER to
                # headings. Ignore it for matching, while retaining raw content.
                title = match.group(1).replace('\u2060', '').strip()
                headings.append((title, offset, offset + len(line)))
        offset += len(line)
    titles = [row[0] for row in headings]
    topic = len(titles) == 3 and all(title in allowed for title, allowed in zip(titles, TOPIC_TITLES))
    if not topic and titles != PERSONAL_TITLES:
        return []
    sections = [
        {"title": title, "body": content[start:headings[i + 1][1] if i + 1 < len(headings) else len(content)].strip()}
        for i, (title, _, start) in enumerate(headings)
    ]
    return sections if all(row["body"] for row in sections) else []


def first_report(messages):
    for message in messages:
        if message.role == "assistant" and (sections := report_sections(message.content)):
            return message, sections
    return None


def require_personal_report(content: str) -> None:
    sections = report_sections(content)
    if [section['title'] for section in sections] != PERSONAL_TITLES:
        raise ValueError('个人报告章节未完整生成，请重新加载报告确认保存状态。')
