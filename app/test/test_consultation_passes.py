from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.models.chat import Conversation, Message
from app.models.consultation import ConsultationPass, ConsultationRequest
from app.services import consultation_passes as service


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (Conversation, Message, ConsultationPass, ConsultationRequest):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([Conversation(id=1, user_id=1, title="工作"), Conversation(id=2, user_id=2, title="他人")])
        session.add(ConsultationPass(id=1, order_id=10, user_id=1, duration_hours=24, reply_limit=2))
        session.commit()
        yield session
    engine.dispose()


NOW = datetime(2026, 10, 2)


def activate(db):
    reading = service.grant_paid(db, SimpleNamespace(id=10, status="PAID"), NOW)
    service.bind(db, 1, reading.id, 1, NOW)
    db.commit()
    return reading


def test_payment_grant_is_idempotent_and_uses_snapshot(db):
    reading = activate(db)
    service.grant_paid(db, SimpleNamespace(id=10, status="PAID"), NOW + timedelta(hours=2))
    assert reading.expires_at == NOW + timedelta(hours=24)
    with pytest.raises(ValueError):
        service.grant_paid(db, SimpleNamespace(id=10, status="CREATED"), NOW)


def test_binding_cannot_cross_accounts_or_change_question(db):
    activate(db)
    with pytest.raises(service.ReadingError):
        service.bind(db, 1, 1, 2, NOW)
    db.add(Conversation(id=3, user_id=1, title="新问题")); db.commit()
    with pytest.raises(service.ReadingError):
        service.bind(db, 1, 1, 3, NOW)


def test_reservation_blocks_parallel_and_success_replays_without_double_use(db):
    reading = activate(db)
    request = service.reserve(db, 1, 1, 1, "request-1", "如何选择", NOW); db.commit()
    with pytest.raises(service.ReadingError):
        service.reserve(db, 1, 1, 1, "request-2", "另一个问题", NOW)
    assert service.finish(db, request.id, "先列清条件", NOW)
    db.commit()
    replay = service.reserve(db, 1, 1, 1, "request-1", "如何选择", NOW)
    assert replay.reply == "先列清条件"
    assert reading.replies_used == 1
    assert db.scalar(select(func.count()).select_from(Message)) == 2
    with pytest.raises(service.ReadingError):
        service.reserve(db, 1, 1, 1, "request-1", "改了内容", NOW)


def test_failure_and_empty_response_do_not_charge(db):
    reading = activate(db)
    request = service.reserve(db, 1, 1, 1, "request-1", "问题", NOW)
    assert not service.finish(db, request.id, "  ", NOW)
    db.commit()
    assert reading.replies_used == 0
    assert db.scalar(select(func.count()).select_from(Message)) == 0
    assert service.reserve(db, 1, 1, 1, "request-2", "问题", NOW).status == "PENDING"


def test_expiry_and_refund_reject_new_requests_and_cancel_inflight(db):
    reading = activate(db)
    with pytest.raises(service.ReadingError):
        service.reserve(db, 1, 1, 1, "request-1", "问题", NOW + timedelta(hours=24))
    request = service.reserve(db, 1, 1, 1, "request-2", "问题", NOW)
    service.revoke(db, 10)
    assert not service.finish(db, request.id, "不能交付", NOW)
    assert reading.replies_used == 0
    with pytest.raises(service.ReadingError):
        service.reserve(db, 1, 1, 1, "request-3", "问题", NOW)


def test_abandoned_request_cannot_complete_after_new_reservation(db):
    reading = activate(db)
    first = service.reserve(db, 1, 1, 1, "request-1", "问题", NOW)
    later = NOW + timedelta(minutes=16)
    second = service.reserve(db, 1, 1, 1, "request-2", "问题", later)
    assert not service.finish(db, first.id, "过期任务", later)
    assert service.finish(db, second.id, "新任务", later)
    assert reading.replies_used == 1


def test_product_rejects_unbounded_or_mixed_legacy_grants():
    product = SimpleNamespace(features={"consultation": {"duration_hours": 24, "reply_limit": 10}}, grants=[], quota_amount=0, bazi_quota=0, liuyao_quota=0)
    assert service.product_terms(product) == (24, 10)
    product.features["consultation"]["reply_limit"] = -1
    with pytest.raises(ValueError): service.product_terms(product)


def test_real_order_snapshots_terms_and_refund_does_not_touch_legacy(db, monkeypatch):
    from app.models import Product, ProductGrant, Order
    from app.services.orders import _create_order
    from app.services.membership_service import apply_paid_product
    from app.services.refunds import finalize_successful_refund
    from app.config import settings
    from sqlalchemy import Integer
    # SQLite auto-increments only INTEGER PRIMARY KEY; production uses MySQL BIGINT.
    monkeypatch.setattr(Order.__table__.c.id, "type", Integer())
    for model in (Product, ProductGrant, Order):
        model.__table__.create(db.get_bind())
    monkeypatch.setattr(settings, 'consultation_enabled', True)
    product = Product(code='LOCAL_TEST', name='测试权益', kind='consultation', price_cents=990,
        quota_amount=0, bazi_quota=0, liuyao_quota=0, currency='CNY',
        features={'consultation': {'duration_hours': 48, 'reply_limit': 3}})
    db.add(product); db.flush()
    order = _create_order(db, user=SimpleNamespace(id=1), product=product)
    reading = db.scalar(select(ConsultationPass).where(ConsultationPass.order_id == order.id))
    product.features = {'consultation': {'duration_hours': 1, 'reply_limit': 1}}
    order.status = 'PAID'
    monkeypatch.setattr('app.services.membership_service.grant_product_entitlements', lambda *_args, **_kwargs: pytest.fail('legacy quota must not be granted'))
    assert apply_paid_product(db, user_id=1, product=product, order=order) == (None, {})
    assert (reading.duration_hours, reading.reply_limit) == (48, 3)
    original_expiry = reading.expires_at
    apply_paid_product(db, user_id=1, product=product, order=order)
    assert reading.expires_at == original_expiry
    refund = SimpleNamespace(status='SUCCESS', order=order, order_id=order.id)
    assert finalize_successful_refund(db, refund=refund)
    assert reading.status == 'REVOKED' and order.status == 'REFUNDED'
    assert finalize_successful_refund(db, refund=refund)


def test_delete_erases_replay_bodies_and_never_releases_used_pass(db):
    reading = activate(db)
    request = service.reserve(db, 1, 1, 1, 'request-1', '私密问题', NOW)
    service.finish(db, request.id, '私密回复', NOW)
    service.erase_conversation(db, 1)
    db.commit()
    assert db.scalar(select(func.count()).select_from(ConsultationRequest)) == 0
    assert reading.status == 'REVOKED' and reading.conversation_id == 1
