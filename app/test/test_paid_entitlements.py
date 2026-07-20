from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.models import MembershipGrant, QuotaLedger
from app.services.membership_service import (
    create_or_renew_membership_for_order,
    grant_product_entitlements,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


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


class PaidEntitlementTests(unittest.TestCase):
    def test_order_quota_grants_create_ledger_entries(self):
        db = _FakeSession([None, None])
        product = SimpleNamespace(
            grants=[
                SimpleNamespace(quota_type="chat", amount=100),
                SimpleNamespace(quota_type="liuyao_chat", amount=100),
            ],
            bazi_quota=0,
            liuyao_quota=0,
            quota_amount=0,
        )
        order = SimpleNamespace(id=42)

        with patch(
            "app.services.membership_service.QuotaService.add_quota"
        ) as add_quota:
            granted = grant_product_entitlements(
                db, user_id=7, product=product, order=order
            )

        self.assertEqual(granted, {"chat": 100, "liuyao_chat": 100})
        ledgers = [item for item in db.added if isinstance(item, QuotaLedger)]
        self.assertEqual(len(ledgers), 2)
        self.assertEqual(
            {item.idempotency_key for item in ledgers},
            {
                "order:42:quota:chat:grant",
                "order:42:quota:liuyao_chat:grant",
            },
        )
        self.assertTrue(all(call.kwargs["commit"] is False for call in add_quota.call_args_list))

    def test_existing_quota_ledger_prevents_duplicate_grant(self):
        db = _FakeSession([SimpleNamespace(id=1)])
        product = SimpleNamespace(
            grants=[SimpleNamespace(quota_type="chat", amount=100)],
            bazi_quota=0,
            liuyao_quota=0,
            quota_amount=0,
        )

        with patch(
            "app.services.membership_service.QuotaService.add_quota"
        ) as add_quota:
            granted = grant_product_entitlements(
                db,
                user_id=7,
                product=product,
                order=SimpleNamespace(id=42),
            )

        self.assertEqual(granted, {})
        self.assertEqual(db.added, [])
        add_quota.assert_not_called()

    def test_membership_renewal_records_order_period(self):
        previous_end = datetime(2026, 8, 1)
        membership = SimpleNamespace(
            current_period_start=datetime(2026, 7, 1),
            current_period_end=previous_end,
            status="active",
            order_id=1,
            cancelled_at=None,
        )
        db = _FakeSession([None, membership])
        product = SimpleNamespace(id=3, period="monthly")

        result = create_or_renew_membership_for_order(
            db,
            user_id=7,
            product=product,
            order=SimpleNamespace(id=42),
        )

        self.assertIs(result, membership)
        grants = [item for item in db.added if isinstance(item, MembershipGrant)]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].starts_at, previous_end)
        self.assertEqual(grants[0].ends_at, datetime(2026, 8, 31))
        self.assertEqual(membership.current_period_end, grants[0].ends_at)
        self.assertEqual(membership.order_id, 42)

    def test_existing_membership_grant_prevents_duplicate_extension(self):
        membership = SimpleNamespace(current_period_end=datetime(2026, 8, 1))
        db = _FakeSession([SimpleNamespace(id=9), membership])

        result = create_or_renew_membership_for_order(
            db,
            user_id=7,
            product=SimpleNamespace(id=3, period="monthly"),
            order=SimpleNamespace(id=42),
        )

        self.assertIs(result, membership)
        self.assertEqual(db.added, [])
        self.assertEqual(membership.current_period_end, datetime(2026, 8, 1))


if __name__ == "__main__":
    unittest.main()
