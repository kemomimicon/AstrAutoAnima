"""Opt-in Studio 0.25 connector host; never installs or executes training code."""
import asyncio
from contextlib import suppress
import hashlib
import secrets
import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import require_admin
from .extensions import registry, contained, read_json, ExtensionManifest

ID = 'anima-lora-studio'
BASE = '/extensions/anima-lora-studio/'
COOKIE = 'aaa_studio_session'
SAFE_HEADERS = {'content-type', 'content-length', 'content-disposition', 'content-range',
                'accept-ranges', 'etag', 'last-modified'}
REQUEST_HEADERS = {'content-type', 'accept', 'range', 'if-range', 'if-none-match',
                   'if-modified-since', 'last-event-id'}
SECURITY = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'self'"}

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

class ExtensionHost:
    def __init__(self, settings, transport=None, clock=time.monotonic):
        self.settings = settings
        self.clock = clock
        self.transport = transport
        self.client = None
        self.codes = {}
        self.sessions = {}

    def upstream(self):
        value = self.settings.anima_studio_upstream.rstrip('/')
        try:
            u = urlsplit(value)
            port = u.port
        except ValueError:
            raise HTTPException(503, '炼丹炉上游端口配置无效') from None
        if (u.scheme != 'http' or u.hostname != '127.0.0.1' or u.username or u.password
                or u.path or u.query or u.fragment or not port):
            raise HTTPException(503, '炼丹炉上游配置无效，仅允许固定 loopback HTTP 端口')
        if port in {self.settings.port, 6185, 8188, 6099}:
            raise HTTPException(503, '炼丹炉上游端口不能指向其他工作站服务')
        return value

    async def start(self):
        self.client = httpx.AsyncClient(transport=self.transport, trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(60, connect=5),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8))

    async def close(self):
        self.codes.clear()
        self.sessions.clear()
        if self.client:
            await self.client.aclose()

    def package(self):
        rows = registry(self.settings.extensions_root)['extensions']
        row = next((r for r in rows if r['id'] == ID and r['enabled']), None)
        if not row or row['state'] == 'broken_package':
            raise HTTPException(404, '炼丹炉连接器未安装或未启用')
        root = contained(self.settings.extensions_root, f"packages/{ID}/{row['version']}")
        manifest = ExtensionManifest.model_validate(read_json(contained(root, 'manifest.json')))
        # Bind sessions to the exact active manifest as well as administrator key.
        stamp = digest((root/'manifest.json').read_text(encoding='utf-8-sig') + self.settings.admin_token)
        return root, manifest, stamp

    async def health(self):
        self.package()
        try:
            response = await self.client.get(self.upstream()+'/api/health', timeout=3)
            value = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            value = {}
        version = str(value.get('version', '')) if isinstance(value, dict) else ''
        if version == '0.25.0' or version.startswith('0.25.'):
            return {'state': 'ready', 'version': version, 'message': '炼丹炉在线，可以连接工作台'}
        if version:
            return {'state': 'incompatible', 'message': '此连接器仅验证 Studio 0.25.x，拒绝未知版本'}
        return {'state': 'upstream_offline', 'message': '炼丹炉未就绪，请检查现有 Studio 服务'}

    def prune(self):
        for store in (self.codes, self.sessions):
            for key, row in list(store.items()):
                if row['expires'] <= self.clock():
                    del store[key]
        if len(self.codes) + len(self.sessions) >= 256:
            raise HTTPException(429, '扩展会话过多，请稍后重试')

    def issue(self):
        _, _, stamp = self.package()
        self.prune()
        code = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        self.codes[digest(code)] = {'stamp': stamp, 'expires': self.clock()+30, 'id': session_id}
        return {'launch_path': BASE+'launch#'+code, 'expires_in': 30, 'session_id': session_id}

    def exchange(self, code):
        _, _, stamp = self.package()
        self.prune()
        row = self.codes.pop(digest(code), None)
        if not row or row['stamp'] != stamp:
            raise HTTPException(401, '启动链接已失效，请重新连接')
        token = secrets.token_urlsafe(32)
        self.sessions[digest(token)] = {'stamp': stamp, 'expires': self.clock()+900,
                                      'deadline': self.clock()+14400, 'id': row['id']}
        return token

    def authorize(self, request):
        package = self.package()
        token = request.cookies.get(COOKIE, '')
        row = self.sessions.get(digest(token))
        now = self.clock()
        if not row or row['expires'] <= now or row['stamp'] != package[2]:
            raise HTTPException(401, '炼丹炉会话已过期，请重新连接')
        row['expires'] = min(now+900, row['deadline'])
        if request.method not in {'GET', 'HEAD'}:
            check_origin(request)
        return package

def check_origin(request):
    expected = str(request.base_url).rstrip('/')
    config = contained(host(request).settings.extensions_root, 'public_origin.json')
    if config.exists():
        value = read_json(config).get('origin', '')
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or '*' in value):
            raise HTTPException(503, '炼丹炉外部来源配置无效')
        expected = value
    if request.headers.get('origin') != expected:
        raise HTTPException(403, '跨来源扩展请求已拒绝')

def host(request):
    return request.app.state.extension_host

admin = APIRouter(prefix='/api/v1/admin/extensions', dependencies=[Depends(require_admin)])
web = APIRouter(prefix=BASE.rstrip('/'))

@admin.post('/anima-lora-studio/session')
async def session(request: Request):
    health = await host(request).health()
    if health['state'] != 'ready':
        raise HTTPException(503, health['message'])
    return JSONResponse(host(request).issue(), headers={'Cache-Control': 'no-store'})

@admin.delete('/anima-lora-studio/sessions')
async def revoke(request: Request):
    host(request).sessions.clear()
    host(request).codes.clear()
    return {'revoked': True}

@admin.post('/anima-lora-studio/sessions/{session_id}/close')
async def close_session(session_id: str, request: Request):
    h = host(request)
    for store in (h.codes, h.sessions):
        for key, row in list(store.items()):
            if row['id'] == session_id:
                del store[key]
    return {'revoked': True}

@web.get('/launch')
async def launch(request: Request):
    host(request).package()
    nonce = secrets.token_urlsafe(16)
    # Fragment never reaches access logs; remove it before any subrequest.
    html = '''<!doctype html><meta charset="utf-8"><title>连接炼丹炉</title>
<p id="status">正在建立管理员会话…</p><script nonce="NONCE">
const code=location.hash.slice(1);history.replaceState(null,'',location.pathname);
fetch('./exchange',{method:'POST',headers:{'Content-Type':'application/json'},
credentials:'same-origin',body:JSON.stringify({code})}).then(r=>{
if(!r.ok)throw Error(String(r.status));location.replace('./');
}).catch(e=>document.getElementById('status').textContent=
e.message==='403'?'服务器拒绝页面来源，请管理员检查 public_origin.json 与当前 HTTPS 地址是否一致':
e.message==='401'?'启动链接已过期或使用过，请返回 App 重新连接':
e.message==='422'?'启动凭据不完整，请从 App 重新进入，不要复制启动链接':
'连接请求失败，请检查网络和 Hub 服务后重新连接');
</script>'''.replace('NONCE', nonce)
    headers = {**SECURITY, 'Content-Security-Policy': SECURITY['Content-Security-Policy'].replace("script-src 'self'", f"script-src 'nonce-{nonce}'")}
    return HTMLResponse(html, headers=headers)

class Exchange(BaseModel):
    code: str = Field(min_length=30, max_length=100)

@web.post('/exchange')
async def exchange(payload: Exchange, request: Request):
    check_origin(request)
    token = host(request).exchange(payload.code)
    response = JSONResponse({'ok': True}, headers=SECURITY)
    response.set_cookie(COOKIE, token, path=BASE, httponly=True,
                        secure=request.url.scheme == 'https' or request.headers.get('origin', '').startswith('https://'), samesite='strict')
    return response

@web.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'], include_in_schema=False)
async def content(path: str, request: Request):
    h = host(request)
    root, manifest, _ = h.authorize(request)
    if any(c in path for c in ('\\', '%', ':')) or any(p in {'.', '..'} for p in path.split('/')) or path.startswith('/'):
        raise HTTPException(400, '无效扩展路径')
    if path.startswith(('api/', 'samples/')):
        if not any(('/'+path).startswith(p) for p in manifest.proxy.path_prefixes):
            raise HTTPException(403, '扩展路径不允许代理')
        headers = {k: v for k,v in request.headers.items() if k.lower() in REQUEST_HEADERS}
        headers['accept-encoding'] = 'identity'
        stream = path == 'api/events'
        timeout = httpx.Timeout(None if stream else 120, connect=5)
        try:
            req = h.client.build_request(request.method, h.upstream()+'/'+path,
                params=request.query_params.multi_items(), headers=headers,
                content=request.stream(), timeout=timeout)
            req.headers.pop('cookie', None)
            req.headers.pop('authorization', None)
            response = await h.client.send(req, stream=True)
        except httpx.TimeoutException:
            raise HTTPException(504, '炼丹炉请求超时') from None
        except httpx.HTTPError:
            raise HTTPException(502, '炼丹炉连接失败') from None
        if 300 <= response.status_code < 400 and response.status_code != 304:
            await response.aclose()
            raise HTTPException(502, '上游重定向已阻止')
        if response.headers.get('content-encoding', 'identity') != 'identity':
            await response.aclose()
            raise HTTPException(502, '上游返回了不支持的压缩传输')
        outgoing = {k:v for k,v in response.headers.items() if k.lower() in SAFE_HEADERS}
        outgoing.update(SECURITY)
        if stream:
            outgoing['X-Accel-Buffering'] = 'no'
        async def chunks():
            pending = None
            try:
                iterator = response.aiter_raw().__aiter__()
                while True:
                    # Check even when an upstream SSE connection is silent.
                    session = h.sessions.get(digest(request.cookies.get(COOKIE,'')), {})
                    try:
                        stamp = h.package()[2]
                    except HTTPException:
                        break
                    if stamp != session.get('stamp') or session.get('expires',0) <= h.clock():
                        break
                    if pending is None:
                        pending = asyncio.create_task(anext(iterator))
                    ready, _ = await asyncio.wait({pending}, timeout=1)
                    if not ready:
                        continue
                    try:
                        chunk = pending.result()
                    except StopAsyncIteration:
                        break
                    pending = None
                    yield chunk
            finally:
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending
                await response.aclose()
        return StreamingResponse(chunks(), status_code=response.status_code, headers=outgoing)
    if request.method not in {'GET', 'HEAD'}:
        raise HTTPException(405, '静态资源只允许读取')
    try:
        webroot = contained(root, manifest.web.root)
        target = contained(webroot, path or manifest.web.index)
        if not target.is_file() and '.' not in path.rsplit('/',1)[-1]:
            target = contained(webroot, manifest.web.index)
        if not target.is_file() or target.name.startswith('.'):
            raise ValueError()
    except (ValueError, OSError):
        raise HTTPException(404, '扩展资源不存在') from None
    return FileResponse(target, headers=SECURITY)
