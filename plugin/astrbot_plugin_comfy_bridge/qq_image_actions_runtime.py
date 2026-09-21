"""Submit a QQ-authorized favorite/report to the local Hub without API secrets."""
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from .workflow_runtime import WorkflowError


async def submit_action(root, hub_url, event, job, index, action, reason=''):
    if event.get_platform_name() != 'aiocqhttp':
        raise WorkflowError('此指令仅用于 QQ 引用图片；客户端请使用图片旁的按钮')
    qq = str(event.get_sender_id())
    if not re.fullmatch(r'[1-9][0-9]{4,14}', qq):
        raise WorkflowError('无法识别你的 QQ 身份')
    url = urlsplit(str(hub_url).rstrip('/'))
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
        raise WorkflowError('QQ 收藏举报的 Hub 地址必须为本机 HTTP 服务地址')
    if action not in {'favorite', 'unfavorite', 'report'} or len(reason) > 500:
        raise WorkflowError('举报说明最多 500 字；无效操作')
    assets = job.get('result', {}).get('assets', [])
    if not 0 <= index < len(assets):
        raise WorkflowError('引用图片序号无效')
    token = uuid.uuid4().hex
    directory = Path(root) / 'hub_state' / 'qq_image_actions'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (token + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump({'action': action, 'qq': qq, 'job_id': job['job_id'], 'asset_id': assets[index],
                   'reason': reason, 'expires_at': time.time() + 60}, stream, ensure_ascii=False)
    os.chmod(path, 0o600)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=False) as session:
            async with session.post(str(hub_url).rstrip('/') + '/api/v1/internal/qq-image-actions/' + token, allow_redirects=False) as response:
                if response.status == 404:
                    raise WorkflowError('Hub 尚未更新，请同步更新插件与 Hub 后再使用 QQ 收藏举报')
                result = await response.json()
                if response.status != 200:
                    raise WorkflowError(str(result.get('detail', '操作失败')))
                return str(result.get('message', '操作已完成'))
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise WorkflowError('Hub 未响应或结果未确认；请检查收藏/举报列表，勿连续重复提交') from exc
