"""Read per-output prompt evidence; never reverse-guess a library entry.

Kept byte-identical to Hub prompt_snapshots.py (covered by a parity test).
Only task metadata is read. Image retention and favorites are independent.
"""
from __future__ import annotations


def image_prompt_snapshot(job, index=0, load_job=None, _seen=()):
    if not isinstance(index, int) or index < 0:
        raise ValueError('图片序号无效')
    identifier = str(job.get('job_id', ''))
    if identifier in _seen or len(_seen) >= 8:
        raise ValueError('任务来源链循环或过长')
    data = job.get('input') or {}
    outputs = (job.get('result') or {}).get('assets') or []
    if outputs and index >= len(outputs):
        raise ValueError('图片序号超出任务输出范围')
    kind = str((job.get('workflow') or {}).get('type', job.get('workflow_type', '')))
    enhance = job.get('enhance') or {}
    # SeedVR2 is an image-only upscaler. Its input prompt is NOT conditioning.
    if kind == 'seedvr2_refine_v1':
        parent = enhance.get('hq_detail_job_id') or enhance.get('hq_base_job_id') or job.get('parent_job_id')
        if parent and load_job:
            original = load_job(str(parent))
            if original:
                if 'source_image_index' not in data and len((original.get('result') or {}).get('assets') or []) > 1:
                    raise ValueError('旧放大任务未记录来源图片序号，不能猜测五连中的哪张图')
                parent_index = int(data.get('source_image_index', index))
                result = image_prompt_snapshot(original, parent_index, load_job, (*_seen, identifier))
                return {**result, 'stage': '来源生图提示词（本次 SeedVR2 放大不使用文本条件）'}
        return {'available': False, 'kind': 'unavailable', 'stage': '纯图像放大，无可追溯的来源提示词', 'positive': '', 'negative': ''}
    entries = data.get('source_entries') or []
    source = entries[0] if len(entries) == 1 else (entries[index] if index < len(entries) else {})
    batch = data.get('batch_prompts') or []
    if batch:
        if index >= len(batch):
            raise ValueError('逐图提示词数量与输出不一致，不能套用第一张')
        positive = str(batch[index]).strip()
    else:
        positive = str(data.get('compiled_prompt') or '').strip()
    complete = bool(positive)
    if not positive and source.get('prompt'):
        positive = ', '.join(str(x).strip(' ,\n\t') for x in
                             (source.get('user_addition', ''), source['prompt']) if str(x).strip(' ,\n\t'))
    code = str(source.get('safety_code') or '').upper()
    if code not in {'N', 'H', 'S'}:
        code = {'normal': 'N', 'nsfw': 'H', 'sexual': 'S'}.get(source.get('safety_level'), '')
    return {
        'available': bool(positive), 'kind': 'compiled' if complete else ('legacy_source' if positive else 'unavailable'),
        'stage': '当次实际正向提示词' if complete else '旧任务仅存原串与附加内容（不是完整生图参数）',
        'positive': positive, 'negative': str(data.get('negative') or '') if complete else '',
        'source_id': str(source.get('id') or ''), 'source_prompt': str(source.get('prompt') or ''),
        'user_addition': str(source.get('user_addition') or ''),
        'edit_request': str(data.get('edit_request') or source.get('edit_request') or ''),
        'safety_code': code, 'job_id': identifier, 'image_index': index,
    }


def format_prompt_snapshot(snapshot):
    if not snapshot.get('available'):
        return '该任务未保存可核对的提示词；不会从图片或词库编号猜测。'
    lines = [snapshot['stage'] + '：', snapshot['positive']]
    if snapshot.get('negative'):
        lines.extend(['\n负向提示词：', snapshot['negative']])
    if snapshot.get('source_id'):
        lines.append('\n来源编号：' + snapshot['source_id'])
    if snapshot.get('user_addition'):
        lines.append('附加内容（已包含在上方，不需重复添加）：' + snapshot['user_addition'])
    if snapshot.get('edit_request'):
        lines.append('本次调整：' + snapshot['edit_request'])
    return '\n'.join(lines)
