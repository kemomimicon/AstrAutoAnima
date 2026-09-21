"""Consume short-lived local capabilities issued by the QQ plugin."""
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path

from .auth import AuthPrincipal
from .lite_users import load_lite_users
from .prompt_likes import promote_k_prompt, remove_prompt_favorite
from .repositories import RepositoryError


def handle_qq_action(settings, reports, jobs, token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise RepositoryError('无效凭据')
    ticket = settings.hub_state_dir / 'qq_image_actions' / (token + '.json')
    if ticket.is_symlink() or not ticket.is_file():
        raise RepositoryError('凭据不存在或已经处理，请重新引用图片发送指令')
    claimed = ticket.with_suffix('.claimed')
    ticket.rename(claimed)
    data = json.loads(claimed.read_text(encoding='utf-8'))
    if float(data.get('expires_at', 0)) < time.time():
        raise RepositoryError('凭据已过期，请重新发送指令')
    qq = str(data.get('qq', ''))
    action = data.get('action')
    if not re.fullmatch(r'[1-9][0-9]{4,14}', qq) or action not in {'favorite', 'unfavorite', 'report'}:
        raise RepositoryError('无效 QQ 身份或操作')
    matches = [user for user in load_lite_users(settings.lite_users_path) if user.qq == qq]
    if matches:
        user = matches[0]
        principal = AuthPrincipal(role='user', subject=user.id, qq=qq, label=user.label)
    elif settings.legacy_lite_qq == qq:
        principal = AuthPrincipal(role='user', subject='legacy-owner', qq=qq)
    elif action == 'report':
        principal = AuthPrincipal(role='user', subject='qq-' + qq, qq=qq)
    else:
        raise RepositoryError('请先让管理员在客户端用户管理中绑定你的 QQ，收藏即可与个人客户端互通')
    job_id, asset_id = str(data.get('job_id', '')), str(data.get('asset_id', ''))
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) for value in (job_id, asset_id)):
        raise RepositoryError('图片任务关联无效')
    store = settings.plugin_data_dir / 'job_store'
    job = json.loads((store / 'jobs' / (job_id + '.json')).read_text(encoding='utf-8-sig'))
    asset = json.loads((store / 'assets' / (asset_id + '.json')).read_text(encoding='utf-8-sig'))
    outputs = job.get('result', {}).get('assets', [])
    if asset.get('job_id') != job_id or asset.get('type') != 'result' or asset_id not in outputs:
        raise RepositoryError('引用图片不属于任务输出')
    entries = job.get('input', {}).get('source_entries', [])
    index = outputs.index(asset_id)
    source = entries[0] if len(entries) == 1 else (entries[index] if len(entries) == len(outputs) else {})
    prompt_id = str(source.get('id', ''))
    if action != 'report' and not prompt_id:
        raise RepositoryError('该图没有可靠的抽取词库编号，不能收藏预设或猜测提示词')
    if action == 'favorite':
        result = promote_k_prompt(settings, prompt_id, principal)
        return {'message': ('已经收藏' if result.action == 'already_liked' else '已收藏') + f'提示词 {prompt_id}，可在客户端个人收藏中查看'}
    if action == 'unfavorite':
        remove_prompt_favorite(settings, prompt_id, principal)
        jobs.unmark_liked(prompt_id, principal)
        return {'message': f'已取消收藏提示词 {prompt_id}（仅影响你的收藏）'}
    path = Path(asset.get('path', ''))
    if not path.is_file() or path.stat().st_size > 64 * 1024**2:
        raise RepositoryError('原图已清理或过大，不能提交图片举报')
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != asset.get('sha256'):
        raise RepositoryError('原图内容与任务记录不一致，拒绝提交错误证据')
    snapshot = {'prompt': source or {'prompt': '无可靠词库编号，仅供图片审核'},
                'command': f'QQ 引用举报｜QQ={qq}｜任务={job_id}｜{str(data.get("reason", ""))[:500]}',
                'qq': qq, 'reason': str(data.get('reason', ''))[:500],
                'content_type': mimetypes.guess_type(path.name)[0] or 'image/png', 'image_sha256': digest}
    result = reports.submit_evidence(job_id, asset_id, principal, prompt_id, snapshot, content)
    return {'message': ('你已经举报过这张图' if result['status'] == 'already_reported' else '已提交管理员审核（不会自动删除词条或扣分）') + f'｜举报={result["id"]}'}
