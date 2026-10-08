"""Bounded user facts and database-managed consultation instructions."""
import json
from typing import Any

FACT_LIMITS = {"topic": 400, "currentSituation": 1200, "options": 800, "timeframe": 100}


def user_facts(context: Any) -> dict[str, str]:
    if not isinstance(context, dict) or context.get("taskType") != "career":
        return {}
    raw = context.get("facts")
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key].strip()[:limit] for key, limit in FACT_LIMITS.items()
            if isinstance(raw.get(key), str) and raw[key].strip()}


def bounded_history(history: list[dict], recent: int = 10) -> list[dict]:
    """Keep the original question/report plus recent turns, without a summary.

    The reader opens the first complete report even after alternatives and many
    follow-ups. Keep that exact assistant source too; it is an earlier AI answer,
    never a user fact or instruction.
    """
    from app.services.conversation_report import report_sections
    valid = [m for m in history if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    original_report = next((m for m in valid if m['role'] == 'assistant' and report_sections(m['content'])), None)
    # Consecutive assistant messages are saved alternatives from regeneration.
    # Keep all originals in the archive, but use the latest answer in the prompt.
    current = []
    for message in valid:
        if current and message['role'] == current[-1]['role'] == 'assistant':
            current[-1] = message
        else:
            current.append(message)
    valid = current
    tail = valid[-max(1, recent):]
    first = next((m for m in valid if m["role"] == "user"), None)
    pinned = []
    if first and not any(m is first for m in tail):
        pinned.append({"role": "user", "content": first["content"][:4000]})
    if original_report and not any(m is original_report for m in tail):
        pinned.append({"role": "assistant", "content": original_report['content']})
    return [*pinned, *tail]


def consultation_context(db, context: Any, history: list[dict]) -> list[dict]:
    if not isinstance(context, dict) or context.get("taskType") != "career":
        return []
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT version, value_json FROM app_config WHERE cfg_key = :key "
        "AND is_active = 1 ORDER BY version DESC LIMIT 1"
    ), {"key": "career_consultation_prompt"}).mappings().first() if db else None
    messages = []
    if row:
        config = row["value_json"]
        if isinstance(config, str):
            config = json.loads(config)
        content = config.get("content") if isinstance(config, dict) else None
        if isinstance(content, str) and content.strip():
            messages.append({"role": "system", "content": content})
            from app.core.logging import get_logger
            get_logger("consultation").info("prompt_selected", version=row["version"], stage="follow_up" if history else "initial")
    facts = user_facts(context)
    if facts:
        # User-supplied data stays in user role, never promoted to system authority.
        messages.append({"role": "user", "content": "本次问题中我明确提供的背景：\n" + json.dumps(facts, ensure_ascii=False)})
    return messages


def bazi_consultation_context(db, context: Any, history: list[dict]) -> list[dict]:
    """Career instructions apply to the opening; later Bazi turns follow the user.

    Keep the saved task and explicit facts, without treating an earlier career
    question as a permanent restriction on subsequent topics.
    """
    follow_up = any(message.get('role') == 'assistant' for message in history)
    messages = consultation_context(None if follow_up else db, context, history)
    if follow_up:
        for message in messages:
            if message['role'] == 'user':
                message['content'] = message['content'].replace(
                    '本次问题中我明确提供的背景：',
                    '此前事业问题中我明确提供的背景（仅在当前问题相关时参考）：',
                    1,
                )
    return messages
