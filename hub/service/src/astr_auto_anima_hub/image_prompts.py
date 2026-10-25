"""Resolve a user's selected image to text evidence, without opening image files."""
import json
import re

from .prompt_snapshots import image_prompt_snapshot
from .prompt_favorites import save_favorite, source_safety_code
from .repositories import RepositoryError


def read_store_record(store, kind, identifier):
    if kind not in {'jobs', 'assets'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', identifier):
        raise RepositoryError('任务记录编号无效')
    path = store / kind / (identifier + '.json')
    if not path.exists():
        return None
    if path.resolve() != path.absolute() or not path.is_file():
        raise RepositoryError('任务记录路径无效')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def resolve_image_prompt(settings, job, image):
    if image.final_prompt:
        return dict(available=True, kind='compiled', positive=image.final_prompt,
                    negative=image.negative_prompt, stage=image.prompt_stage or '当次实际正向提示词',
                    source_id=image.prompt_id, user_addition=image.user_addition,
                    safety_code=image.source_safety_code)
    store = settings.plugin_data_dir / 'job_store'
    load_job = lambda identifier: read_store_record(store, 'jobs', identifier)
    matches = []
    suite_job = next((row.get('job_id') for row in job.task_suite_rows
                      if row.get('index') == image.task_suite_index), None) if image.task_suite_index else None
    for identifier in job.bridge_job_ids:
        if suite_job and identifier != suite_job:
            continue
        source = load_job(identifier)
        if not source:
            continue
        for index, asset_id in enumerate((source.get('result') or {}).get('assets') or []):
            asset = read_store_record(store, 'assets', str(asset_id))
            if asset and asset.get('type') == 'result' and asset.get('job_id') == identifier and asset.get('sha256') == image.sha256:
                try:
                    matches.append(image_prompt_snapshot(source, index, load_job))
                except (ValueError, TypeError) as exc:
                    raise RepositoryError(str(exc)) from exc
    if matches:
        identity = lambda s: (s.get('positive'), s.get('negative'), s.get('source_id'), s.get('user_addition'))
        if len({identity(s) for s in matches}) != 1:
            raise RepositoryError('图片对应多份不同任务快照，不能猜测；请引用原任务消息查询')
        return matches[0]
    # Local execution records have no AstrBot jobs; they already freeze the
    # final workflow text. Do not use a job-wide text for remote batches.
    if settings.execution_mode == 'local' and job.final_prompt:
        return dict(available=True, kind='compiled', positive=job.final_prompt, negative='',
                    stage='当次实际正向提示词', source_id=image.prompt_id,
                    user_addition=image.user_addition, safety_code=image.source_safety_code)
    if image.source_prompt:
        return image_prompt_snapshot({'job_id': job.id, 'input': {'source_entries': [dict(
            id=image.prompt_id, prompt=image.source_prompt, user_addition=image.user_addition,
            safety_code=image.source_safety_code)]}})
    return dict(available=False, kind='unavailable', positive='', negative='',
                stage='旧任务未保存可核对的提示词')


def save_image_prompt(settings, principal, snapshot, reference):
    if not snapshot.get('available'):
        raise RepositoryError('该图未保存可靠的提示词，不能从词库编号猜测收藏内容')
    if snapshot.get('kind') == 'legacy_source':
        # Compatibility: old source-only snapshots stay explicitly source-only.
        # Never invent an N classification for an unclassified legacy record.
        code = source_safety_code(snapshot, required=True)
    else:
        # Arbitrary direct/edited text has not necessarily been classified.
        # Unknown content is conservatively S, never silently downgraded to N.
        code = snapshot.get('safety_code') or 'S'
    source_id = snapshot.get('source_id') or reference
    return save_favorite(settings.prompt_favorites_path, principal,
        {'id': source_id, 'name': source_id, 'prompt': snapshot['positive'], 'safety_code': code})
