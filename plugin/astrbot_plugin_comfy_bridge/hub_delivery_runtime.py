"""One-use, local Hub capabilities for per-image OneBot delivery receipts."""
import base64
import hashlib
import json
import re
import time
from pathlib import Path

from .workflow_runtime import WorkflowError


async def deliver_ticket(context, store, root, token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise WorkflowError('无效的投递凭据')
    path = Path(root) / 'hub_state' / 'qq_deliveries' / (token + '.json')
    if path.is_symlink() or not path.is_file():
        raise WorkflowError('投递凭据不存在或已被使用')
    claimed = path.with_suffix('.claimed')
    path.rename(claimed)
    result = {'status': 'failed', 'message': '投递尚未完成，禁止自动重发'}
    try:
        data = json.loads(claimed.read_text(encoding='utf-8'))
        if data.get('action') != 'deliver' or float(data.get('expires_at', 0)) < time.time():
            raise WorkflowError('投递凭据已过期')
        umo = str(data.get('umo', ''))
        match = re.fullmatch(r'([^:]+):(GroupMessage|FriendMessage):([0-9_]+)', umo)
        if not match:
            raise WorkflowError('投递会话无效')
        platform_id, kind, session_id = match.groups()
        adapter = context.get_platform_inst(platform_id)
        if adapter is None or adapter.meta().name != 'aiocqhttp':
            raise WorkflowError('目标 QQ 实例未就绪')
        asset = store.get_asset(str(data['asset_id']))
        job = store.get_job(str(asset['job_id']))
        ids = job.get('result', {}).get('assets', [])
        if asset.get('type') != 'result' or asset['asset_id'] not in ids:
            raise WorkflowError('图片不属于任务输出')
        content = Path(asset['path']).read_bytes()
        if hashlib.sha256(content).hexdigest() != data.get('sha256') or asset.get('sha256') != data['sha256']:
            raise WorkflowError('投递图片与审核后的图片不一致')
        bot = adapter.get_client()
        login = await bot.call_action('get_login_info')
        login = login.get('data', login)
        self_id = str(login.get('user_id', ''))
        if not self_id.isdigit():
            raise WorkflowError('无法确认 QQ 机器人身份')
        target = session_id.split('_')[-1] if kind == 'GroupMessage' else session_id
        if not target.isdigit():
            raise WorkflowError('QQ 目标无效')
        message = []
        from .delivery_runtime import basic_image_caption
        original = job.get('input', {})
        options = original.get('generation_options', {})
        entries = original.get('source_entries', [])
        image_index = ids.index(asset['asset_id'])
        entry = entries[0] if len(entries) == 1 else (entries[image_index] if image_index < len(entries) else {})
        caption = basic_image_caption({'character_name': options.get('character'), 'style_name': options.get('style')}, options, entry)
        message.append({'type': 'text', 'data': {'text': caption}})
        message.append({'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(content).decode()}})
        receipt = await bot.call_action('send_group_msg' if kind == 'GroupMessage' else 'send_private_msg',
            **{'group_id' if kind == 'GroupMessage' else 'user_id': int(target), 'self_id': self_id, 'message': message})
        receipt = receipt.get('data', receipt)
        message_id = receipt.get('message_id')
        if message_id is None:
            raise WorkflowError('图片投递回执缺失；可能已发送，禁止自动重发')
        store.record_delivery(str(message_id), umo + '\0' + self_id, job['job_id'], ids.index(asset['asset_id']))
        result = {'status': 'sent', 'message_id': str(message_id)}
    except Exception as exc:
        result['message'] = str(exc)[:500]
        raise
    finally:
        temporary = path.with_suffix('.result.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path.with_suffix('.result.json'))
