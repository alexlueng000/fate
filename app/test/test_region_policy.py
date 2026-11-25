import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import region


class RegionPolicyTests(unittest.TestCase):
    def test_overseas_cannot_enable_domestic_payments(self):
        with patch.object(region, 'settings', SimpleNamespace(fate_region='overseas', fate_payments_enabled=True)):
            self.assertFalse(region.payments_enabled())
            with self.assertRaises(ValueError):
                region.require_payment_service()

    def test_cn_default_and_explicit_disable(self):
        for enabled in [True, False]:
            with patch.object(region, 'settings', SimpleNamespace(fate_region='cn', fate_payments_enabled=enabled)):
                self.assertEqual(region.payments_enabled(), enabled)

    def test_rejection_happens_before_payment_handler(self):
        from fastapi import Depends
        from app.i18n import LocaleMiddleware
        app = FastAPI()
        app.add_middleware(LocaleMiddleware)
        called = []
        @app.post('/payments/simulate', dependencies=[Depends(region.require_payments)])
        def checkout():
            called.append(True)
            return {'ok': True}
        with patch.object(region, 'settings', SimpleNamespace(fate_region='overseas', fate_payments_enabled=True)):
            response = TestClient(app).post('/payments/simulate', headers={'Accept-Language': 'zh-TW'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], '此地區暫未開放付款。')
        self.assertEqual(called, [])
