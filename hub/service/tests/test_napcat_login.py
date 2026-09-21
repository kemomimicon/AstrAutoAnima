import hashlib
import unittest
from unittest.mock import patch
import httpx
from astr_auto_anima_hub.napcat_login import napcat_request, NapcatLoginRequest


class NapcatTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_only_skips_accounts_and_offline_wins(self):
        client_type = httpx.AsyncClient
        seen = []
        def handler(request):
            seen.append(request.url.path)
            if request.url.path.endswith('/auth/login'):
                data = {'Credential': 'private-credential'}
            elif request.url.path.endswith('/CheckLoginStatus'):
                data = {'isLogin': True, 'isOffline': True}
            else:
                raise AssertionError('status must not depend on account list')
            return httpx.Response(200, json={'code': 0, 'data': data})
        with patch.dict('os.environ', {'AAH_NAPCAT_TOKEN': 'unit-secret', 'AAH_NAPCAT_URL': 'http://127.0.0.1:6099'}), patch('astr_auto_anima_hub.napcat_login.httpx.AsyncClient', side_effect=lambda **kw: client_type(**kw, transport=httpx.MockTransport(handler))):
            result = await napcat_request(NapcatLoginRequest(), status_only=True)
        self.assertEqual(result['state'], 'offline')
        self.assertFalse(result['is_login'])
        self.assertEqual(len(seen), 2)
        self.assertNotIn('private-credential', str(result))

    def test_missing_status_is_unknown_not_offline(self):
        from astr_auto_anima_hub.napcat_login import login_state
        self.assertEqual(login_state({}), 'unknown')
        self.assertEqual(login_state({'isLogin': False}), 'not_logged_in')
        self.assertEqual(login_state({'isLogin': True}), 'online')

    async def test_accounts_qr_and_no_credentials_returned(self):
        client_type = httpx.AsyncClient
        def handler(request):
            if request.url.path.endswith('/auth/login'):
                data = {'Credential': 'private-credential'}
            elif request.url.path.endswith('/CheckLoginStatus'):
                self.assertEqual(request.headers['Authorization'], 'Bearer private-credential')
                data = {'isLogin': False, 'qrcodeurl': 'https://qq.example/login'}
            else:
                data = ['123456', '1234567', 'invalid']
            return httpx.Response(200, json={'code': 0, 'data': data})
        with patch.dict('os.environ', {'AAH_NAPCAT_TOKEN': 'unit-secret', 'AAH_NAPCAT_URL': 'http://127.0.0.1:6099'}), patch('astr_auto_anima_hub.napcat_login.httpx.AsyncClient', side_effect=lambda **kw: client_type(**kw, transport=httpx.MockTransport(handler))):
            result = await napcat_request(NapcatLoginRequest())
        self.assertEqual(result['accounts'], ['123456', '1234567'])
        self.assertEqual(result['qr_code'], 'https://qq.example/login')
        self.assertNotIn('private-credential', str(result))
        self.assertNotIn('unit-secret', str(result))

    async def test_2fa_is_not_bypassed(self):
        client_type = httpx.AsyncClient
        seen = []
        def handler(request):
            seen.append(request.url.path)
            self.assertIn(hashlib.sha256(b"unit-secret.napcat").hexdigest(), request.content.decode())
            return httpx.Response(200, json={"code": 0, "data": {"require2FA": True}})
        with patch.dict("os.environ", {"AAH_NAPCAT_TOKEN": "unit-secret", "AAH_NAPCAT_URL": "http://127.0.0.1:6099"}), patch("astr_auto_anima_hub.napcat_login.httpx.AsyncClient", side_effect=lambda **kw: client_type(**kw, transport=httpx.MockTransport(handler))):
            result = await napcat_request(NapcatLoginRequest(uin="123456"), login=True)
        self.assertTrue(result["require_2fa"])
        self.assertEqual(seen, ["/api/auth/login"])
        self.assertNotIn("unit-secret", str(result))

    async def test_external_url_rejected(self):
        with patch.dict("os.environ", {"AAH_NAPCAT_TOKEN": "unit-secret", "AAH_NAPCAT_URL": "https://example.com"}):
            with self.assertRaises(ValueError):
                await napcat_request(NapcatLoginRequest())
