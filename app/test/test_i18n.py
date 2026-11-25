import asyncio
import unittest
from app.i18n import LocaleMiddleware, current_locale, resolve_locale, output_language_rule, auth_message


class LocaleTests(unittest.TestCase):
    def test_auth_errors_preserve_default_and_unknown_messages(self):
        self.assertEqual(auth_message('邮箱或密码错误'), '邮箱或密码错误')
        token = current_locale.set('zh-TW')
        try:
            self.assertEqual(auth_message('邮箱或密码错误'), '電子郵件或密碼錯誤')
            self.assertEqual(auth_message('opaque-code'), 'opaque-code')
        finally:
            current_locale.reset(token)
    def test_prompt_default_unchanged_and_language_switch(self):
        self.assertEqual(output_language_rule(), '')
        token = current_locale.set('zh-TW')
        try:
            self.assertIn('台灣繁體中文', output_language_rule())
            self.assertIn('JSON key', output_language_rule())
        finally:
            current_locale.reset(token)
        self.assertEqual(output_language_rule(), '')
    def test_negotiation(self):
        for header, expected in [('', 'zh-CN'), ('en', 'zh-CN'),
                                 ('zh-TW', 'zh-TW'), ('zh-Hant-TW', 'zh-TW'),
                                 ('zh-TW;q=0,zh-CN', 'zh-CN'),
                                 ('zh-CN;q=0.2,zh-TW;q=0.9', 'zh-TW'),
                                 ('zh-TW;q=invalid', 'zh-CN')]:
            self.assertEqual(resolve_locale(header), expected)

    def test_concurrent_stream_context_and_cleanup(self):
        async def run():
            observed = {}
            async def endpoint(scope, receive, send):
                await asyncio.sleep(0)
                observed[scope['id']] = current_locale.get()
                await send({'type': 'http.response.body', 'body': b'data: ok\n\n'})
            middleware = LocaleMiddleware(endpoint)
            async def send(message):
                await asyncio.sleep(0)
            async def request(identifier, locale):
                await middleware({'type': 'http', 'id': identifier,
                                  'headers': [(b'accept-language', locale)]}, None, send)
                self.assertEqual(current_locale.get(), 'zh-CN')
            await asyncio.gather(request('tw', b'zh-TW'), request('cn', b'zh-CN'))
            self.assertEqual(observed, {'tw': 'zh-TW', 'cn': 'zh-CN'})
        asyncio.run(run())
