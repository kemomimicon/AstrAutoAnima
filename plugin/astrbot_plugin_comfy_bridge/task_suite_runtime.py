"""Run one prepared prompt through an immutable ordered preset snapshot."""
from __future__ import annotations
import copy
import json
import os
import re
import secrets
import time
import hashlib
import uuid
from pathlib import Path

try:
    from .workflow_runtime import WorkflowError
except ImportError:
    from workflow_runtime import WorkflowError


def suite_token(options):
    value = str(options.get('style', ''))
    if not value.startswith('__hub_suite_'):
        return ''
    token = value.removeprefix('__hub_suite_')
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise WorkflowError('套组凭据无效')
    return token


def bind_qq_suite(plugin, event, options):
    """Resolve a named suite only for the sender's uniquely bound QQ account."""
    if getattr(event, 'get_platform_name', lambda: '')() != 'aiocqhttp':
        raise WorkflowError('套组名称指令仅供 QQ 使用，客户端请使用套组选择器')
    root = plugin._character_dictionary_path().parent / 'hub_state'
    registry = root / 'lite_users.json'
    subject = ''
    if registry.is_file():
        users = json.loads(registry.read_text('utf-8-sig')).get('users', [])
        found = [u for u in users if u.get('enabled', True) and str(u.get('qq', '')) == str(event.get_sender_id())]
        if len(found) == 1:
            subject = str(found[0]['id'])
    path = root / 'task_suites.json'
    if not path.is_file() or path.is_symlink():
        raise WorkflowError('尚无任务套组，请在客户端预设页新增')
    items = json.loads(path.read_text('utf-8-sig')).get('items', {}).values()
    found = [s for s in items if s.get('name') == options['task_suite'] and (s.get('scope') == 'global' or (subject and s.get('owner') == subject))]
    if len(found) != 1:
        raise WorkflowError('套组不存在、重名或无权使用，请在客户端检查名称及 QQ 绑定')
    suite = found[0]
    presets = json.loads(plugin._preset_path().read_text('utf-8-sig'))
    rows = []
    for source in suite['rows']:
        character = source['character']
        snapshot = None
        if source['character_kind'] == 'preset':
            snapshot = presets.get('characters', {}).get(character)
            if not isinstance(snapshot, dict) or snapshot.get('hidden') or snapshot.get('disabled') or snapshot.get('enabled', True) is False:
                raise WorkflowError(f'角色预设已失效：{character}')
        if source['character_kind'] == 'favorite':
            favorites = json.loads((root / 'character_favorites.json').read_text('utf-8-sig')).get('users', {}).get('user:' + subject, [])
            if not any(f.get('tag') == character for f in favorites):
                raise WorkflowError('收藏角色已失效')
            from .character_dictionary_runtime import resolve_character
            match = resolve_character(plugin._character_dictionary_path(), character, mode='strong', edits_path=root / 'character_dictionary_edits.json')
            if match is None:
                raise WorkflowError('收藏角色无法解析')
            character = match.prompt
        style_key = source['style']
        if source['style_kind'] == 'personal':
            if not subject or suite['scope'] == 'global' or style_key not in {'1', '2', '3'}:
                raise WorkflowError('私人画风不可用')
            style_key = f"__hub_personal_{hashlib.sha256(subject.encode()).hexdigest()[:14]}_{style_key}"
        style = presets.get('styles', {}).get(style_key)
        if not isinstance(style, dict) or style.get('disabled') or style.get('enabled', True) is False or (source['style_kind'] == 'global' and style.get('hidden')):
            raise WorkflowError('画风预设已失效')
        rows.append(dict(character=character, style=style_key, character_kind=source['character_kind'], character_snapshot=snapshot, style_snapshot=style))
    token = uuid.uuid4().hex
    runs = root / 'task_suite_runs'
    runs.mkdir(parents=True, exist_ok=True)
    with (runs / f'{token}.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(id=suite['id'], name=suite['name'], rows=rows, rows_status=['queued'] * len(rows), expires_at=time.time()+86400), stream, ensure_ascii=False)
    return {**options, 'style': '__hub_suite_' + token, 'character': '__suite_replace_identity__'}


def load_run(root, token):
    path = Path(root) / 'hub_state' / 'task_suite_runs' / f'{token}.json'
    if not path.is_file() or path.is_symlink():
        raise WorkflowError('套组凭据已失效')
    data = json.loads(path.read_text(encoding='utf-8'))
    if float(data.get('expires_at', 0)) < time.time() or not 1 <= len(data.get('rows', [])) <= 20:
        raise WorkflowError('套组过期或行数无效')
    return path, data


def save_progress(path, data):
    temp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
    os.replace(temp, path)


def row_options(options, row, run, index):
    result = copy.deepcopy(options)
    for key in ('_copy_character', '_copy_style', '_restore_lora_stack', 'character_variant',
                'character_strength', 'character_model', 'character_clip', 'style_scale', '_random_preset'):
        result.pop(key, None)
    result.update(character=row['character'], style=row['style'], character_tag_mode='strong',
                  _copy_style=copy.deepcopy(row['style_snapshot']), _suite_row=True,
                  _task_suite={'id': run['id'], 'name': run['name'], 'index': index + 1, 'total': len(run['rows'])})
    if isinstance(row.get('character_snapshot'), dict):
        result['_copy_character'] = copy.deepcopy(row['character_snapshot'])
    if not options.get('fixed_seed'):
        result['_fixed_seed'] = secrets.randbelow(2**32)
    return result


async def execute_suite(plugin, event, prompt, options, kwargs):
    token = suite_token(options)
    path, run = load_run(plugin._character_dictionary_path().parent, token)
    if run.get('started'):
        raise WorkflowError('套组已开始执行，拒绝重复提交')
    try:
        with path.with_suffix('.claim').open('x', encoding='utf-8') as stream:
            stream.write(str(time.time()))
    except FileExistsError as exc:
        raise WorkflowError('套组已开始执行，拒绝重复提交') from exc
    run['started'] = True
    run['prompt'] = prompt
    save_progress(path, run)
    await event.send(event.plain_result(f"套组任务已创建：{run['name']}，共 {len(run['rows'])} 项，逐项生成。"))
    succeeded = 0
    for index, row in enumerate(run['rows']):
        if path.with_suffix('.cancel').exists() or time.time() > run['expires_at']:
            run['rows_status'][index:] = ['cancelled'] * (len(run['rows']) - index)
            save_progress(path, run)
            break
        run['rows_status'][index] = 'running'
        save_progress(path, run)
        try:
            child = row_options(options, row, run, index)
            ok = await plugin._deliver_generation(event, prompt=prompt, options=child,
                **{**kwargs, 'allow_character_text_fallback': True,
                   'completion_prefix': f"套组 {index+1}/{len(run['rows'])}"})
            run['rows_status'][index] = 'succeeded' if ok else 'failed'
            succeeded += bool(ok)
            run.setdefault('row_job_ids', {})[str(index)] = child.get('_suite_result_job_id', '')
        except Exception as exc:
            run['rows_status'][index] = 'failed'
            await event.send(event.plain_result(f'套组第 {index+1} 项失败：{exc}'))
        save_progress(path, run)
    await event.send(event.plain_result(f"套组结束：成功 {succeeded}/{len(run['rows'])} 项。"))
    return succeeded > 0
