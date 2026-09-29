from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest import TestCase
from unittest.mock import Mock, patch
import base64
import json
import time

import httpx
from jose import jwt, JWTError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from app.services import wechat_jsapi as jsapi


class JsapiTests(TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = self.key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
        config = SimpleNamespace(
            wechat_jsapi_enabled=True, wechat_pay_mode='prod',
            wechat_jsapi_appid='wx_public_account', wechat_jsapi_secret='test-secret',
            wechat_jsapi_origins='https://fateinsight.site', jwt_secret='x' * 32,
            wechat_api_v3_key='k' * 32,
            wechat_pay_mchid='merchant', wechat_pay_merchant_serial_no='serial',
            wechat_pay_notify_url='https://api.fateinsight.site/api/webhooks/wechatpay',
            wechat_pay_private_key_pem=pem, wechat_pay_private_key_path=None,
            wechat_platform_public_key_pem='test-platform-key', wechat_platform_public_key_path=None,
        )
        for target in (jsapi, jsapi.payments):
            patcher = patch.object(target, 'settings', config)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = config

    def authorize(self, uri='https://fateinsight.site/membership'):
        return jsapi.authorize(user_id=7, product_code='PLAN', redirect_uri=uri)

    def test_authorization_binds_user_product_and_state(self):
        result = self.authorize()
        query = parse_qs(urlsplit(result['url']).query)
        self.assertEqual(query['appid'], ['wx_public_account'])
        self.assertEqual(query['scope'], ['snsapi_base'])
        self.assertEqual(query['state'], [result['state']])
        self.assertLessEqual(len(result['state']), 128)
        self.assertEqual(jsapi.validate_ticket(user_id=7, ticket=result['ticket'], state=result['state']), 'PLAN')
        for user, state in [(8, result['state']), (7, 'wrong')]:
            with self.assertRaises(ValueError):
                jsapi.validate_ticket(user_id=user, ticket=result['ticket'], state=state)
        with self.assertRaises(JWTError):
            jwt.decode(result['ticket'], self.config.jwt_secret, algorithms=['HS256'])

    def test_expired_ticket_rejected(self):
        token = jwt.encode({'sub': '7', 'nonce': 'n', 'product_code': 'PLAN',
                            'aud': 'wechat-jsapi', 'exp': int(time.time()) - 20},
                           jsapi._ticket_key(), algorithm='HS256')
        with self.assertRaises(ValueError):
            jsapi.validate_ticket(user_id=7, ticket=token, state='n')

    def test_rejects_untrusted_redirects(self):
        for uri in ['https://evil.example/membership', 'http://fateinsight.site/membership',
                    'https://fateinsight.site.evil.example/membership',
                    'https://fateinsight.site/membership?redirect=evil',
                    'https://fateinsight.site/login', 'https://user@fateinsight.site/pricing']:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                self.authorize(uri)

    def test_disabled_and_dev_fail_closed(self):
        self.config.wechat_jsapi_enabled = False
        with self.assertRaises(ValueError):
            self.authorize()
        self.config.wechat_jsapi_enabled = True
        self.config.wechat_pay_mode = 'dev'
        with self.assertRaises(ValueError):
            self.authorize()

    def test_bridge_signature_matches_official_message(self):
        params = jsapi.payment_params('wx-prepay')
        message = '\n'.join([params['appId'], params['timeStamp'], params['nonceStr'], params['package'], ''])
        self.key.public_key().verify(base64.b64decode(params['paySign']), message.encode(),
                                     padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(params['signType'], 'RSA')

    @patch.object(jsapi.httpx, 'Client')
    def test_oauth_error_does_not_expose_secret(self, client):
        client.return_value.__enter__.return_value.get.return_value = httpx.Response(
            200, json={'errcode': 40029, 'errmsg': 'secret-value'})
        with self.assertRaisesRegex(ValueError, '微信授权失败'):
            jsapi.exchange_openid('expired-code')

    @patch.object(jsapi.payments, 'verify_wechat_response')
    @patch.object(jsapi.httpx, 'Client')
    def test_checkout_amount_and_appid_are_server_controlled(self, client, verify):
        post = client.return_value.__enter__.return_value.post
        post.return_value = httpx.Response(200, json={'prepay_id': 'wx-prepay'})
        order = SimpleNamespace(id=3, status='CREATED', out_trade_no='order-3', amount_cents=1990,
                                currency='CNY', product=SimpleNamespace(name='高级套餐'))
        db = Mock()
        payment, params = jsapi.create_prepay(db, order=order, openid='public-openid')
        request = json.loads(post.call_args.kwargs['content'])
        self.assertEqual(request['appid'], 'wx_public_account')
        self.assertEqual(request['payer'], {'openid': 'public-openid'})
        self.assertEqual(request['amount'], {'total': 1990, 'currency': 'CNY'})
        self.assertEqual(payment.channel, 'WECHAT_JSAPI')
        self.assertEqual(params['package'], 'prepay_id=wx-prepay')
        verify.assert_called_once()
        db.add.assert_called_once_with(payment)
        verify.side_effect = ValueError('bad signature')
        db.reset_mock()
        with self.assertRaises(ValueError):
            jsapi.create_prepay(db, order=order, openid='public-openid')
        db.add.assert_not_called()
