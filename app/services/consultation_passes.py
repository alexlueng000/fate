"""Transaction boundaries belong to callers; serialize by pass and conversation."""
from datetime import datetime, timedelta
import hashlib
from sqlalchemy import select, delete, update, inspect
from app.models.consultation import ConsultationPass, ConsultationRequest
from app.models.chat import Conversation, Message


class ReadingError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def product_terms(product):
    features = product.features if isinstance(product.features, dict) else {}
    terms = features.get("consultation", {})
    if not isinstance(terms, dict):
        raise ValueError("问题解读商品配置格式无效")
    hours, limit = terms.get("duration_hours"), terms.get("reply_limit")
    if type(hours) is not int or type(limit) is not int or not 1 <= hours <= 720 or not 1 <= limit <= 100:
        raise ValueError("问题解读商品必须配置有效期（1–720 小时）及成功回复上限（1–100）")
    if product.grants or product.quota_amount or product.bazi_quota or product.liuyao_quota:
        raise ValueError("问题解读商品不可同时发放旧次数权益")
    return hours, limit


def prepare_order(db, order, product):
    hours, limit = product_terms(product)
    db.add(ConsultationPass(order_id=order.id, user_id=order.user_id, duration_hours=hours, reply_limit=limit))
    db.flush()


def grant_paid(db, order, now=None):
    if order.status != "PAID":
        raise ValueError("订单尚未支付")
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.order_id == order.id).with_for_update())
    if not reading:
        raise ValueError("问题解读订单缺少权益快照")
    if reading.status == "PENDING":
        now = now or datetime.utcnow()
        reading.status = "ACTIVE"
        reading.starts_at = now
        reading.expires_at = now + timedelta(hours=reading.duration_hours)
    return reading


def revoke(db, order_id):
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.order_id == order_id).with_for_update())
    if not reading:
        raise ValueError("问题解读订单缺少权益快照")
    reading.status = "REVOKED"


def erase_conversation(db, conversation_id):
    """Remove private replay bodies along with the user's deleted conversation."""
    if not inspect(db.connection()).has_table(ConsultationRequest.__tablename__):
        return
    db.execute(delete(ConsultationRequest).where(ConsultationRequest.conversation_id == conversation_id))
    # Keep order audit data but never make a used pass transferable after deletion.
    db.execute(update(ConsultationPass).where(ConsultationPass.conversation_id == conversation_id).values(status="REVOKED"))


def owned_conversation(db, user_id, conversation_id, lock=False):
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    conversation = db.scalar(stmt.with_for_update() if lock else stmt)
    if not conversation:
        raise ReadingError("解读记录不存在", 404)
    return conversation


def available(reading, now):
    return reading.status == "ACTIVE" and reading.expires_at is not None and now < reading.expires_at


def bind(db, user_id, pass_id, conversation_id, now=None):
    owned_conversation(db, user_id, conversation_id, lock=True)
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.id == pass_id, ConsultationPass.user_id == user_id).with_for_update())
    if not reading:
        raise ReadingError("解读权益不存在", 404)
    if reading.conversation_id not in (None, conversation_id):
        raise ReadingError("这份权益已用于另一个问题")
    if not available(reading, now or datetime.utcnow()):
        raise ReadingError("权益已到期或不可用", 402)
    reading.conversation_id = conversation_id
    return reading


def reserve(db, user_id, conversation_id, pass_id, request_key, message, now=None):
    now = now or datetime.utcnow()
    owned_conversation(db, user_id, conversation_id, lock=True)
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.id == pass_id, ConsultationPass.user_id == user_id).with_for_update())
    if not reading or reading.conversation_id != conversation_id:
        raise ReadingError("请先将解读权益用于当前问题", 403)
    digest = hashlib.sha256(message.encode()).hexdigest()
    previous = db.scalar(select(ConsultationRequest).where(ConsultationRequest.user_id == user_id, ConsultationRequest.request_key == request_key))
    if previous:
        if previous.input_hash != digest or previous.pass_id != pass_id or previous.conversation_id != conversation_id:
            raise ReadingError("请求标识已用于另一条消息")
        if previous.status == "SUCCEEDED":
            return previous
        if previous.status == "PENDING" and previous.created_at > now - timedelta(minutes=15):
            raise ReadingError("这条解读仍在生成，请稍候")
    if not available(reading, now) or reading.replies_used >= reading.reply_limit:
        raise ReadingError("本次权益已到期或回复额度已用完；历史内容仍可查看", 402)
    pending = db.scalars(select(ConsultationRequest).where(ConsultationRequest.conversation_id == conversation_id, ConsultationRequest.status == "PENDING")).all()
    for item in pending:
        if item.created_at > now - timedelta(minutes=15):
            raise ReadingError("当前问题已有一条解读正在生成")
        item.status = "FAILED"
    if previous:
        # A failed key is not reused while an old worker might still be completing.
        raise ReadingError("上次请求未完成，请重新提交并使用新的请求标识")
    reservation = ConsultationRequest(pass_id=pass_id, user_id=user_id, conversation_id=conversation_id,
        request_key=request_key, input_hash=digest, user_message=message, created_at=now)
    db.add(reservation)
    db.flush()
    return reservation


def finish(db, request_id, reply=None, now=None):
    # Same lock order as reserve: conversation, pass, then request.
    initial = db.get(ConsultationRequest, request_id)
    if not initial:
        return False
    conversation = owned_conversation(db, initial.user_id, initial.conversation_id, lock=True)
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.id == initial.pass_id).with_for_update())
    reservation = db.scalar(select(ConsultationRequest).where(ConsultationRequest.id == request_id).with_for_update().execution_options(populate_existing=True))
    if reservation.status != "PENDING":
        return reservation.status == "SUCCEEDED"
    now = now or datetime.utcnow()
    if not reply or not reply.strip() or reading.status != "ACTIVE" or reservation.created_at <= now - timedelta(minutes=15):
        reservation.status = "FAILED"
        reservation.completed_at = now
        return False
    # Time validity was checked at reservation; permit an in-flight reply to finish.
    reservation.status = "SUCCEEDED"
    reservation.reply = reply
    reservation.completed_at = now
    reading.replies_used += 1
    conversation.updated_at = now
    for role, content in (("user", reservation.user_message), ("assistant", reply)):
        db.add(Message(conversation_id=reservation.conversation_id, user_id=reservation.user_id, role=role, content=content))
    db.flush()
    return True
