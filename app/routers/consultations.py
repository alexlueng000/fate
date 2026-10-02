"""Explicit opt-in reading-pass API. Never consumes legacy quota."""
from datetime import datetime, timedelta
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db, SessionLocal
from app.deps import get_current_user
from app.models import User
from app.models.chat import Message
from app.models.consultation import ConsultationPass, ConsultationRequest
from app.services import consultation_passes as passes

router = APIRouter(prefix="/consultations", tags=["consultations"])


@router.get("/features")
def features():
    return {"enabled": settings.consultation_enabled}


def enabled():
    if not settings.consultation_enabled:
        raise HTTPException(404, "Not found")


def serialize(reading):
    return {"id": reading.id, "order_id": reading.order_id, "conversation_id": reading.conversation_id,
        "status": reading.status, "expires_at": reading.expires_at.isoformat() + "Z" if reading.expires_at else None,
        "duration_hours": reading.duration_hours, "reply_limit": reading.reply_limit,
        "remaining": max(0, reading.reply_limit - reading.replies_used),
        "available": passes.available(reading, datetime.utcnow()) and reading.replies_used < reading.reply_limit}


@router.get("/catalog/products")
def catalog(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enabled()
    from app.models import Product
    result = []
    for product in db.scalars(select(Product).where(Product.kind == "consultation", Product.active.is_(True))):
        try:
            hours, limit = passes.product_terms(product)
        except ValueError:
            continue
        result.append({"code": product.code, "name": product.name, "price_cents": product.price_cents,
            "duration_hours": hours, "reply_limit": limit, "description": product.description})
    return result


@router.get("/{conversation_id}")
def status(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enabled()
    try:
        conversation = passes.owned_conversation(db, user.id, conversation_id)
    except passes.ReadingError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    readings = db.scalars(select(ConsultationPass).where(ConsultationPass.user_id == user.id,
        (ConsultationPass.conversation_id == conversation_id) | ConsultationPass.conversation_id.is_(None),
        ConsultationPass.status != "PENDING").order_by(ConsultationPass.id.desc())).all()
    return {"conversation_id": conversation_id, "question": conversation.title, "passes": [serialize(r) for r in readings]}


@router.get("/{conversation_id}/requests/{request_key}")
def request_status(conversation_id: int, request_key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enabled()
    item = db.scalar(select(ConsultationRequest).where(ConsultationRequest.user_id == user.id,
        ConsultationRequest.conversation_id == conversation_id, ConsultationRequest.request_key == request_key))
    if not item:
        raise HTTPException(404, "请求记录不存在")
    status = "EXPIRED" if item.status == "PENDING" and item.created_at <= datetime.utcnow() - timedelta(minutes=15) else item.status
    return {"status": status}


class BindIn(BaseModel):
    pass_id: int = Field(gt=0)


@router.post("/{conversation_id}/bind")
def bind(conversation_id: int, body: BindIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enabled()
    try:
        reading = passes.bind(db, user.id, body.pass_id, conversation_id)
        db.commit()
        return serialize(reading)
    except passes.ReadingError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc)) from exc


class MessageIn(BaseModel):
    pass_id: int = Field(gt=0)
    request_key: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)


def build_messages(db, conversation, message):
    from app.chat import utils
    from app.chat.consultation import bounded_history, consultation_context
    from app.chat.rag import retrieve_kb
    from app.liuyao.prompts import build_system_prompt
    from app.models.liuyao import LiuyaoHexagram
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)).all()
    history = [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "assistant")]
    kind = "liuyao" if conversation.liuyao_hexagram_id else "bazi"
    try:
        passages = retrieve_kb(message, kb_type=kind)
    except Exception:
        passages = []
    if kind == "liuyao":
        hexagram = db.get(LiuyaoHexagram, conversation.liuyao_hexagram_id)
        if not hexagram:
            raise passes.ReadingError("原卦象已不存在，请开始新的问题", 409)
        system = build_system_prompt(hexagram, passages, utils.load_liuyao_system_prompt_from_db())
    else:
        snapshot = conversation.bazi_chart_snapshot or {}
        paipan = snapshot.get("mingpan", snapshot)
        if not paipan.get("four_pillars"):
            raise passes.ReadingError("原命盘信息不完整，请开始新的问题", 409)
        system = utils.build_full_system_prompt(utils.load_system_prompt_from_db(), passages, paipan=paipan)
    return [{"role": "system", "content": system}, *consultation_context(db, conversation.task_context, history),
            *bounded_history(history), {"role": "user", "content": message}]


@router.post("/{conversation_id}/messages")
def send(conversation_id: int, body: MessageIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enabled()
    from app.chat.sse import sse_pack, sse_response
    from app.chat.deepseek_client import call_deepseek_stream, set_caller
    from app.chat.utils import IncrementalNormalizer
    if not body.message.strip():
        raise HTTPException(422, "请输入问题")
    try:
        reservation = passes.reserve(db, user.id, conversation_id, body.pass_id, body.request_key, body.message.strip())
        if reservation.status == "SUCCEEDED":
            return sse_response(lambda: iter([sse_pack({"text": reservation.reply, "replace": True}), sse_pack("[DONE]")]))
        reservation_id = reservation.id
        messages = build_messages(db, passes.owned_conversation(db, user.id, conversation_id), body.message.strip())
        db.commit()
    except passes.ReadingError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc)) from exc

    def generate():
        completed = False
        normalizer = IncrementalNormalizer(normalize_interval=50)
        try:
            set_caller("consultation_pass")
            for delta in call_deepseek_stream(messages, require_complete=True):
                if delta:
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack({"text": clean, "replace": True})
            final = normalizer.finalize().strip()
            with SessionLocal() as session:
                completed = passes.finish(session, reservation_id, final)
                session.commit()
            if not completed:
                raise ValueError("empty or revoked reading")
            # Invalidate old in-memory copies; existing chat routes can recover DB history.
            try:
                from app.chat.store import delete_conv
                for prefix in ("bazi_conv_", "liuyao_conv_", "conv_"):
                    delete_conv(f"{prefix}{conversation_id}")
            except Exception:
                # A cache outage must not misreport an already committed reply as free failure.
                pass
            yield sse_pack({"text": final, "replace": True})
            yield sse_pack("[DONE]")
        except Exception:
            message = ("保存结果暂时无法确认，请刷新记录与权益后再决定是否重试。" if completed
                       else "本次解读未完成，请重试；未消耗成功回复额度。")
            yield sse_pack({"error": message})
        finally:
            if not completed:
                with SessionLocal() as session:
                    passes.finish(session, reservation_id)
                    session.commit()
    return sse_response(generate)
