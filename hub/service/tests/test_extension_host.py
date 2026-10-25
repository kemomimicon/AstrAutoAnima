"""Host integration against a fake Studio; never imports or starts training."""
import json
import unittest
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import test_extensions
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.extension_host import ExtensionHost, admin, web, BASE, COOKIE


class BytesStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'first\n'
        yield b'second\n'


class HostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_extensions.ExtensionDiscoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.package, _ = self.fixture.package()
        self.settings = Settings(admin_token='a'*32, lite_token='b'*32,
                                 extensions_override=self.fixture.root)
        self.requests = []
        self.now = 0

        async def upstream(request):
            self.requests.append(request)
            if request.url.path == '/api/health':
                return httpx.Response(200, json={'status': 'ok', 'version': '0.25.0'})
            if request.url.path == '/api/redirect':
                return httpx.Response(302, headers={'Location': 'http://example.com/'})
            if request.url.path == '/api/upload':
                body = await request.aread()
                return httpx.Response(200, stream=OneChunk(body))
            return httpx.Response(200, stream=BytesStream(), headers={
                'content-type': 'text/event-stream', 'set-cookie': 'leak=bad'})

        self.host = ExtensionHost(self.settings, httpx.MockTransport(upstream), lambda: self.now)

        @asynccontextmanager
        async def lifespan(app):
            await self.host.start()
            try:
                yield
            finally:
                await self.host.close()

        app = FastAPI(lifespan=lifespan)
        app.state.settings = self.settings
        app.state.extension_host = self.host
        app.include_router(admin)
        app.include_router(web)
        self.client = self.enterContext(TestClient(app))
        self.auth = {'Authorization': 'Bearer ' + self.settings.admin_token}

    def login(self):
        r = self.client.post('/api/v1/admin/extensions/anima-lora-studio/session', headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        path = r.json()['launch_path']
        self.assertNotIn(self.settings.admin_token, path)
        code = path.split('#')[1]
        r = self.client.post(BASE+'exchange', json={'code': code}, headers={'Origin': 'http://testserver'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('HttpOnly', r.headers['set-cookie'])
        self.assertIn('SameSite=strict', r.headers['set-cookie'])
        return code

    def test_admin_only_and_anonymous_denied(self):
        for token in ('', 'b'*32):
            r = self.client.post('/api/v1/admin/extensions/anima-lora-studio/session',
                                 headers={'Authorization': 'Bearer '+token})
            self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.get(BASE+'api/projects').status_code, 401)

    def test_login_replay_and_static(self):
        code = self.login()
        self.assertEqual(self.client.get(BASE).text, 'Mock only')
        self.assertEqual(self.client.get(BASE+'projects/1').text, 'Mock only')
        r = self.client.post(BASE+'exchange', json={'code': code}, headers={'Origin': 'http://testserver'})
        self.assertEqual(r.status_code, 401)

    def test_csrf_and_expiration(self):
        self.login()
        for origin in ('', 'https://evil.example'):
            r = self.client.post(BASE+'api/upload', headers={'Origin': origin}, content=b'test')
            self.assertEqual(r.status_code, 403)
        self.now = 901
        self.assertEqual(self.client.get(BASE).status_code, 401)

    def test_explicit_https_origin_behind_http_proxy(self):
        origin = 'https://studio.example.org'
        (self.fixture.root/'public_origin.json').write_text(json.dumps({'origin': origin}))
        path = self.client.post('/api/v1/admin/extensions/anima-lora-studio/session', headers=self.auth).json()['launch_path']
        code = path.split('#')[1]
        for bad in ('http://testserver', 'null', 'https://evil.example', origin+'.evil.example'):
            r = self.client.post(BASE+'exchange', json={'code':code}, headers={'Origin':bad})
            self.assertEqual(r.status_code,403)
        r = self.client.post(BASE+'exchange', json={'code':code}, headers={'Origin':origin})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('Secure',r.headers['set-cookie'])
        self.client.cookies.set(COOKIE,r.cookies.get(COOKIE))
        r = self.client.post(BASE+'api/upload',content=b'hello',headers={'Origin':origin})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.post(BASE+'api/upload',content=b'hello',headers={'Origin':'https://evil.example'}).status_code,403)

    def test_stream_and_credential_stripping(self):
        self.login()
        r = self.client.get(BASE+'api/events', headers=self.auth)
        self.assertEqual(r.content, b'first\nsecond\n')
        self.assertNotIn('set-cookie', r.headers)
        self.assertEqual(r.headers['x-accel-buffering'], 'no')
        self.assertNotIn('authorization', self.requests[-1].headers)
        self.assertNotIn('cookie', self.requests[-1].headers)

    def test_multipart_body_preserved(self):
        self.login()
        r = self.client.post(BASE+'api/upload', files={'file': ('a.txt', b'hello')},
                             headers={'Origin': 'http://testserver'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'hello', r.content)
        self.assertIn('multipart/form-data', self.requests[-1].headers['content-type'])

    def test_disable_and_revoke(self):
        self.login()
        r = self.client.delete('/api/v1/admin/extensions/anima-lora-studio/sessions', headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(BASE).status_code, 401)
        self.login()
        (self.fixture.root/'active.json').write_text(json.dumps({'schema_version': 1, 'extensions': {}}))
        self.assertEqual(self.client.get(BASE).status_code, 404)

    def test_traversal_and_redirect(self):
        self.login()
        self.assertEqual(self.client.get(BASE+'api/redirect').status_code, 502)
        for path in ('api/%252e%252e/private', 'api/a%5cb', 'api/http:evil'):
            self.assertEqual(self.client.get(BASE+path).status_code, 400)

    def test_upstream_is_loopback_only(self):
        for url in ('http://example.com:8765', 'http://127.0.0.1:8188',
                    'http://127.0.0.1:bad', 'http://user:password@127.0.0.1:8765',
                    'http://127.0.0.1:8765/api'):
            self.host.settings = Settings(anima_studio_upstream=url)
            with self.assertRaises(HTTPException):
                self.host.upstream()


class OneChunk(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data
