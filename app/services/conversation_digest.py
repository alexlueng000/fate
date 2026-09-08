"""Bounded, on-demand summaries, outside the chat persistence path."""
import json
import logging
import threading
from datetime import datetime
import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update, text
from app.config import settings
from app.db import SessionLocal
from app.models.chat import Message
from app.models.conversation_digest import ConversationDigest

logger = logging.getLogger(__name__)
SLOTS = threading.BoundedSemaphore(2)
TOPICS = {"CAREER", "WEALTH", "RELATIONSHIP", "SELF", "FAMILY", "STUDY", "HEALTH", "OTHER"}


class DigestOutput(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    topic: str
    question: str = Field(min_length=2, max_length=400)
    summary: str = Field(min_length=2, max_length=1000)

    @field_validator("title", "question", "summary", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("topic")
    @classmethod
    def topic_fallback(cls, value):
        return value if value in TOPICS else "OTHER"


def build_source(messages):
    # Preserve chronology; bound request size without claiming full coverage.
    result, size, covered = [], 0, 0
    for message in reversed(messages):
        if message.role not in ("user", "assistant"):
            continue
        text = message.content.strip()
        if not text:
            continue
        if size + len(text) > 24000:
            break
        result.append({"role": message.role, "content": text})
        size += len(text)
        covered = max(covered, message.id)
    return list(reversed(result)), covered


def generate_digest(conversation_id: int, token: str):
    acquired = SLOTS.acquire(blocking=False)
    try:
        if not acquired or not settings.deepseek_api_key:
            raise RuntimeError("summary_unavailable")
        with SessionLocal() as db:
            digest = db.get(ConversationDigest, conversation_id)
            if not digest or digest.request_token != token:
                return
            messages = db.scalars(select(Message).where(
                Message.conversation_id == conversation_id,
                Message.role.in_(["user", "assistant"]),
            ).order_by(Message.id.desc()).limit(80)).all()
            # Summarize the most recent bounded window, retaining message provenance.
            source, covered = build_source(list(reversed(messages)))
            config = db.execute(text(
                "SELECT value_json FROM app_config WHERE cfg_key = :key AND is_active = 1 ORDER BY version DESC LIMIT 1"
            ), {"key": "history_digest_prompt"}).scalar()
            if isinstance(config, str):
                config = json.loads(config)
            prompt = config.get("content") if isinstance(config, dict) else None
            if not prompt:
                raise RuntimeError("summary_prompt_missing")
        if not any(row["role"] == "assistant" for row in source):
            raise RuntimeError("no_reading")
        with httpx.Client(timeout=45) as client:
            response = client.post(settings.deepseek_api_url, headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
            }, json={"model": settings.deepseek_model, "temperature": 0,
                     "max_tokens": 1200, "response_format": {"type": "json_object"},
                     "messages": [{"role": "system", "content": prompt},
                                  {"role": "user", "content": json.dumps(source, ensure_ascii=False)}]})
            response.raise_for_status()
            body = response.json()
        output = DigestOutput.model_validate_json(body["choices"][0]["message"]["content"])
        usage = body.get("usage", {})
        with SessionLocal() as db:
            # Conditional update never recreates deleted metadata or overwrites custom titles.
            db.execute(update(ConversationDigest).where(
                ConversationDigest.conversation_id == conversation_id,
                ConversationDigest.request_token == token,
            ).values(**output.model_dump(), status="ready", source_message_id=covered,
                     generated_at=datetime.utcnow(), model=settings.deepseek_model,
                     prompt_tokens=int(usage.get("prompt_tokens", 0)),
                     completion_tokens=int(usage.get("completion_tokens", 0))))
            db.commit()
    except Exception as exc:
        # Never log private conversation content or provider response bodies.
        logger.warning("history_digest_failed id=%s error_type=%s", conversation_id, type(exc).__name__)
        with SessionLocal() as db:
            db.execute(update(ConversationDigest).where(
                ConversationDigest.conversation_id == conversation_id,
                ConversationDigest.request_token == token,
            ).values(status="failed"))
            db.commit()
    finally:
        if acquired:
            SLOTS.release()
