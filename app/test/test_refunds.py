from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.models import (
    MembershipGrant,
    Order,
    Product,
    QuotaLedger,
    Refund,
    UserMembership,
    UserQuota,
)
from app.services.refunds import (
    RefundNotAllowed,
    create_full_refund_request,
    finalize_successful_refund,
    submit_wechat_refund,
    sync_refund_state,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value

    def all(self):
        if self.value is None:
            return []
        if isinstance(self.value, list):
            return self.value
        return [self.value]


class _FakeSession:
    def __init__(self, results):
        self.results = iter(results)
        self.added = []
        self.flush_count = 0

    def execute(self, _statement):
        return _ScalarResult(next(self.results))

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


def _paid_order():
    return SimpleNamespace(
        id=42,
        user_id=7,
        amount_cents=3990,
        currency="CNY",
        status="PAID",
    )


class RefundRequestTests(unittest.TestCase):
    def test_creates_full_refund_and_marks_order_refunding(self):
        order = _paid_order()
        payment = SimpleNamespace(transaction_id="wx_transaction_1")
        db = _FakeSession([order, None, payment])

        refund = create_full_refund_request(
            db,
            order_id=order.id,
            requested_by=99,
            reason=" 用户申请退款 ",
        )

        self.assertIsInstance(refund, Refund)
        self.assertEqual(refund.refund_cents, 3990)
        self.assertEqual(refund.total_cents, 3990)
        self.assertEqual(refund.reason, "用户申请退款")
        self.assertEqual(refund.status, "CREATED")
        self.assertEqual(refund.requested_by, 99)
        self.assertEqual(order.status, "REFUNDING")
        self.assertEqual(db.added, [refund])
        self.assertEqual(db.flush_count, 1)

    def test_duplicate_request_returns_existing_refund(self):
        order = _paid_order()
        order.status = "REFUNDING"
        existing = SimpleNamespace(id=8, status="CREATED")
        db = _FakeSession([order, existing])

        refund = create_full_refund_request(
            db,
            order_id=order.id,
            requested_by=99,
            reason="重复申请",
        )

        self.assertIs(refund, existing)
        self.assertEqual(db.added, [])
        self.assertEqual(db.flush_count, 0)

    def test_rejects_unpaid_order(self):
        order = _paid_order()
        order.status = "CREATED"
        db = _FakeSession([order, None])

        with self.assertRaisesRegex(RefundNotAllowed, "不能申请退款"):
            create_full_refund_request(
                db,
                order_id=order.id,
                requested_by=99,
                reason="未支付退款",
            )

    def test_rejects_order_without_successful_wechat_payment(self):
        order = _paid_order()
        db = _FakeSession([order, None, None])

        with self.assertRaisesRegex(RefundNotAllowed, "微信支付交易记录"):
            create_full_refund_request(
                db,
                order_id=order.id,
                requested_by=99,
                reason="支付记录缺失",
            )

    def test_dev_submission_uses_stable_refund_number(self):
        refund = Refund(
            id=8,
            order_id=42,
            user_id=7,
            out_refund_no="RF202607200001",
            refund_cents=3990,
            total_cents=3990,
            currency="CNY",
            reason="用户申请退款",
            status="CREATED",
        )
        db = _FakeSession([SimpleNamespace(transaction_id="wx_transaction_1")])

        with patch("app.services.refunds.settings.wechat_pay_mode", "dev"):
            result = submit_wechat_refund(db, refund=refund)

        self.assertIs(result, refund)
        self.assertEqual(refund.status, "PROCESSING")
        self.assertEqual(refund.wechat_refund_id, "dev_refund_8")
        self.assertIn('"out_refund_no":"RF202607200001"', refund.raw_request)

    def test_success_state_is_idempotent(self):
        refund = Refund(
            order_id=42,
            user_id=7,
            out_refund_no="RF202607200001",
            refund_cents=3990,
            total_cents=3990,
            currency="CNY",
            status="PROCESSING",
        )
        db = _FakeSession([])

        with patch(
            "app.services.refunds.finalize_successful_refund",
            return_value=True,
        ):
            sync_refund_state(
                db,
                refund=refund,
                data={"refund_id": "wx_refund_1", "status": "SUCCESS"},
                raw_response='{"status":"SUCCESS"}',
            )
            first_success_at = refund.success_at
            sync_refund_state(
                db,
                refund=refund,
                data={"refund_id": "wx_refund_1", "refund_status": "SUCCESS"},
                raw_response='{"refund_status":"SUCCESS"}',
            )
            sync_refund_state(
                db,
                refund=refund,
                data={"refund_id": "wx_refund_1", "status": "PROCESSING"},
                raw_response='{"status":"PROCESSING"}',
            )

        self.assertEqual(refund.status, "SUCCESS")
        self.assertEqual(refund.wechat_refund_id, "wx_refund_1")
        self.assertIsNotNone(first_success_at)
        self.assertEqual(refund.success_at, first_success_at)

    def test_successful_refund_reclaims_only_unused_quota(self):
        product = Product(
            id=3,
            code="topup_100",
            kind="topup",
            name="叠加包",
            price_cents=3990,
            currency="CNY",
            quota_amount=0,
            bazi_quota=100,
            liuyao_quota=0,
            active=True,
        )
        order = Order(
            id=42,
            user_id=7,
            product_id=3,
            amount_cents=3990,
            currency="CNY",
            status="REFUNDING",
            out_trade_no="ORDER42",
            product=product,
        )
        refund = Refund(
            id=8,
            order_id=42,
            user_id=7,
            out_refund_no="RF42",
            refund_cents=3990,
            total_cents=3990,
            currency="CNY",
            status="SUCCESS",
            order=order,
        )
        purchase = QuotaLedger(
            user_id=7,
            quota_type="chat",
            delta=100,
            event_type="PURCHASE_GRANT",
            order_id=42,
            idempotency_key="order:42:quota:chat:grant",
        )
        quota = UserQuota(
            user_id=7,
            quota_type="chat",
            total_quota=110,
            used_quota=50,
            period="never",
            source="purchase",
        )
        db = _FakeSession([[purchase], None, None, quota])

        finalized = finalize_successful_refund(db, refund=refund)

        self.assertTrue(finalized)
        self.assertEqual(quota.total_quota, 50)
        reversals = [
            item
            for item in db.added
            if isinstance(item, QuotaLedger)
            and item.event_type == "REFUND_REVERSAL"
        ]
        self.assertEqual(len(reversals), 1)
        self.assertEqual(reversals[0].delta, -100)
        self.assertIn("reclaimed=60", reversals[0].note)
        self.assertIn("unrecovered=40", reversals[0].note)
        self.assertEqual(order.status, "REFUNDED")

    def test_successful_refund_revokes_only_its_membership_period(self):
        product = Product(
            id=3,
            code="monthly",
            kind="subscription",
            period="monthly",
            name="月卡",
            price_cents=3990,
            currency="CNY",
            quota_amount=0,
            bazi_quota=0,
            liuyao_quota=0,
            active=True,
        )
        order = Order(
            id=42,
            user_id=7,
            product_id=3,
            amount_cents=3990,
            currency="CNY",
            status="REFUNDING",
            out_trade_no="ORDER42",
            product=product,
        )
        refund = Refund(
            id=8,
            order_id=42,
            user_id=7,
            out_refund_no="RF42",
            refund_cents=3990,
            total_cents=3990,
            currency="CNY",
            status="SUCCESS",
            order=order,
        )
        grant = MembershipGrant(
            user_id=7,
            order_id=42,
            product_id=3,
            starts_at=datetime(2026, 8, 1),
            ends_at=datetime(2026, 8, 31),
            status="ACTIVE",
        )
        membership = UserMembership(
            user_id=7,
            product_id=3,
            order_id=99,
            status="active",
            current_period_start=datetime(2026, 7, 1),
            current_period_end=datetime(2026, 9, 30),
            auto_renew=False,
        )
        db = _FakeSession([[], grant, membership])

        finalized = finalize_successful_refund(db, refund=refund)

        self.assertTrue(finalized)
        self.assertEqual(grant.status, "REVOKED")
        self.assertEqual(grant.refund_id, 8)
        self.assertEqual(membership.current_period_end, datetime(2026, 8, 31))
        self.assertEqual(order.status, "REFUNDED")


if __name__ == "__main__":
    unittest.main()
