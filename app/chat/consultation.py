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
    """Retain the original question as a user message, without inventing a summary."""
    valid = [m for m in history if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    tail = valid[-recent:]
    first = next((m for m in valid[:-recent] if m["role"] == "user"), None)
    if first:
        return [{"role": "user", "content": first["content"][:4000]}, *tail]
    return tail


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
