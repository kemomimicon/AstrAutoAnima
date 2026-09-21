"""Deliver a verified Hub image through the plugin's receipt-aware QQ sender."""
import json
import re
import time
import uuid


async def deliver_image(settings, client, umo, text, digest, bridge_ids):
    assets = settings.plugin_data_dir / 'job_store' / 'assets'
    allowed = set(bridge_ids)
    matches = []
    for path in assets.glob('img_*.json'):
        if path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if data.get('sha256') == digest and data.get('job_id') in allowed and data.get('type') == 'result':
                matches.append(data)
        except (OSError, ValueError):
            continue
    if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('图片已保存在记录，但 QQ 投递任务关联不唯一或缺失；未猜测、未发送')
    token = uuid.uuid4().hex
    root = settings.hub_state_dir / 'qq_deliveries'
    root.mkdir(parents=True, exist_ok=True)
    ticket = root / (token + '.json')
    with ticket.open('x', encoding='utf-8') as stream:
        json.dump({'action': 'deliver', 'umo': umo, 'text': text,
                   'asset_id': matches[0]['asset_id'], 'sha256': digest,
                   'expires_at': time.time() + 180}, stream, ensure_ascii=False)
    async with client.stream('POST', '/api/v1/chat', json={
        'username': 'aaa_delivery', 'session_id': 'hub_delivery_' + token,
        'message': '/aaa_hub_deliver ' + token, 'enable_streaming': True,
    }) as response:
        response.raise_for_status()
        async for _ in response.aiter_lines():
            pass
    result_path = ticket.with_suffix('.result.json')
    if not result_path.is_file():
        raise ValueError('QQ 投递未确认，请检查插件是否已同步更新；禁止自动重发')
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if result.get('status') != 'sent':
        raise ValueError(str(result.get('message') or 'QQ 投递失败'))
    return result
