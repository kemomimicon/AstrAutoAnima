"""Bounded, explicit first-image checks. No credential redirects or automatic POST retries."""
from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from first_run_config import SetupError, validate_api_key, validate_dictionary, validate_url

CHARACTERS_URL = 'https://raw.githubusercontent.com/tcpassos/mcp-danbooru-characters/master/data/characters.jsonl'
TRANSLATIONS_URL = 'https://raw.githubusercontent.com/ffdkj/ffdkj-Danbooru_Tag-Chinese-English-Translation-Table/main/tag.sqlite'
TEST_PROMPT = '1girl, solo, adult woman, standing, fully clothed, long coat, park, daylight'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_bytes(base, path, token='', payload=None, limit=20 * 1024 * 1024):
    base = validate_url(base)
    parsed = urlsplit(base)
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = parsed.hostname == 'localhost'
    if token and parsed.scheme != 'https' and not local:
        raise SetupError('密钥检测只允许本机 HTTP 或 HTTPS。不要把密钥经明文网络发送到其他机器。')
    if not path.startswith('/') or path.startswith('//') or '\\' in path:
        raise SetupError('请求路径不合法。')
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token.strip()
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(base + path, data=body, headers=headers)
    try:
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=20) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise SetupError('响应超过大小限制；请在 App 查看，不自动保存。')
        return data
    except urllib.error.HTTPError as exc:
        hints = {401: '令牌未通过验证。AstrBot Key 不要填 12 位前缀；Hub 要用管理员令牌。',
                 403: '权限不足。核对 AstrBot chat / file / im 权限或 Hub 用户权限。',
                 404: '接口或任务不存在。核对地址、版本及任务是否来自当前 Hub。',
                 422: '参数或目标不被接受。检查启用的投递目标及插件配置。'}
        raise SetupError(f'HTTP {exc.code}：' + hints.get(exc.code, '服务拒绝请求，请检查本机日志。不要公开含密钥的日志。')) from None
    except (OSError, urllib.error.URLError):
        raise SetupError('请求未完成。检查服务和地址；若刚提交生图，任务可能已经创建，请先在 App 记录中检查，不要重复提交。') from None


def request_json(*args, **kwargs):
    try:
        data = json.loads(request_bytes(*args, **kwargs))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError):
        raise SetupError('服务响应不是预期 JSON 对象，请检查地址和版本。') from None


def check_astrbot(base, key):
    request_json(base, '/api/v1/chat/sessions?username=aaa_first_run_probe', validate_api_key(key, required=True))
    return 'AstrBot chat 鉴权通过。尚未证明附件权限、QQ 投递或模型推理可用。'


def check_workflow(base, path):
    try:
        workflow = json.loads(Path(path).read_text('utf-8-sig'))
    except (OSError, ValueError):
        raise SetupError('无法读取工作流 JSON。请选择 AAA 插件当前配置的 API 格式工作流。') from None
    if not isinstance(workflow, dict) or not workflow or 'nodes' in workflow:
        raise SetupError('需要 API 格式工作流，而不是包含 nodes 的编辑器格式。')
    info = request_json(base, '/object_info')
    stats = request_json(base, '/system_stats')
    issues = []
    for ident, node in workflow.items():
        if not isinstance(node, dict) or 'class_type' not in node:
            issues.append(f'节点 {ident} 格式无效'); continue
        schema = info.get(node['class_type'])
        if not schema:
            issues.append(f'缺少节点：{node["class_type"]}'); continue
        specs = {**schema.get('input', {}).get('required', {}), **schema.get('input', {}).get('optional', {})}
        for key, value in node.get('inputs', {}).items():
            spec = specs.get(key)
            if isinstance(value, str) and isinstance(spec, list) and spec and isinstance(spec[0], list) and value not in spec[0]:
                issues.append(f'节点 {ident} / {key}：选项或模型不存在：{value}')
    devices = stats.get('devices', [])
    gpu = any(x.get('type') == 'cuda' for x in devices if isinstance(x, dict))
    heading = '检测到 CUDA 设备。' if gpu else '未报告 CUDA 设备；无卡环境不要进行首次生图。'
    return heading + '\n' + ('\n'.join(issues[:40]) if issues else '节点类型和枚举模型名称检查通过；不代表模型文件完整或显存足够。')


def targets(base, token):
    data = request_json(base, '/api/v1/lite/delivery-targets', token)
    rows = data.get('targets')
    if not isinstance(rows, list):
        raise SetupError('Hub 未返回目标列表，请核对 Hub 版本。')
    return [x for x in rows if isinstance(x, dict) and isinstance(x.get('id'), str) and isinstance(x.get('label'), str)]


def submit_test(base, token, target_id, deliver=False):
    if not target_id:
        raise SetupError('请先读取并选择一个实际投递目标。即使不发 QQ，也需要有效目标。')
    return request_json(base, '/api/v1/lite/jobs', token, payload={
        'kind': 'direct', 'target_id': target_id, 'deliver_to_im': bool(deliver),
        'prompt': TEST_PROMPT, 'safety_code': 'N', 'five_draw': False,
        'character': '', 'style': '', 'sampler': 'original'})


def job_path(job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise SetupError('任务 ID 应为 Hub 返回的 32 位十六进制字符串。')
    return '/api/v1/lite/jobs/' + job_id


def job_status(base, token, job_id):
    return request_json(base, job_path(job_id), token)


def fetch_image(base, token, job):
    if job.get('status') != 'succeeded' or not job.get('images'):
        raise SetupError('任务尚未成功返回图片，不能标记完整生图完成。')
    item = job['images'][0]
    image_id = item.get('id', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', image_id):
        raise SetupError('返回的图片 ID 不合法。')
    # Never follow a server-provided arbitrary download URL with the admin credential.
    data = request_bytes(base, job_path(job['id']) + '/images/' + image_id, token)
    if hashlib.sha256(data).hexdigest() != item.get('sha256') or len(data) != item.get('size_bytes'):
        raise SetupError('图片大小或 SHA256 校验失败，请检查传输。')
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        width, height = struct.unpack('>II', data[16:24])
        preview = 0 < width <= 8192 and 0 < height <= 8192 and width * height <= 20000000
        return data, '.png', preview
    if data.startswith(b'\xff\xd8\xff'):
        return data, '.jpg', False
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return data, '.webp', False
    raise SetupError('不是受支持的图片数据，未保存。')


def build_online_dictionary(progress=lambda text: None):
    # Import the existing project builder, not a second incompatible format.
    builder_dir = Path(__file__).resolve().parents[1] / 'plugin/astrbot_plugin_comfy_bridge/tools'
    if builder_dir.is_dir() and str(builder_dir) not in sys.path:
        sys.path.insert(0, str(builder_dir))
    from build_character_dictionary import build_dictionary
    with tempfile.TemporaryDirectory(prefix='aaa-dictionary-') as temp:
        paths = []
        for url, name in [(CHARACTERS_URL, 'characters.jsonl'), (TRANSLATIONS_URL, 'tag.sqlite')]:
            progress('正在下载公开数据：' + name + '，可能需要数分钟…')
            opener = urllib.request.build_opener(NoRedirect())
            path = Path(temp) / name
            with opener.open(url, timeout=60) as response, path.open('xb') as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 300 * 1024 * 1024:
                        raise SetupError('源文件超过 300 MB 上限，下载已停止。')
                    output.write(chunk)
                    progress(f'{name}：已下载 {total // 1024 // 1024} MB')
            paths.append(path)
        progress('校验并装配角色词典，不覆盖运行文件…')
        result = build_dictionary(*paths)
    if validate_dictionary(result) < 1000:
        raise SetupError('公共词典少于 1000 条，拒绝安装，请检查上游格式。')
    result['source'] = {'characters': CHARACTERS_URL, 'translations': TRANSLATIONS_URL}
    return result
