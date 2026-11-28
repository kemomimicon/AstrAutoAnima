"""Reusable favorite text, independent of the actual generation prompt.

Only frozen pre-preset text is eligible. Never recover a prompt by looking up
today's main prompt library or by dropping a guessed prefix from compiled text.
"""
import json
import re
from functools import lru_cache

from .character_catalog import load_character_catalog
from .prompt_favorites import full_prompt
from .prompt_snapshots import image_prompt_snapshot
from .repositories import RepositoryError


def _parts(text):
    parts, start, depth, escaped = [], 0, 0, False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        elif char in ',，' and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _key(text):
    return ' '.join(text.replace('\\(', '(').replace('\\)', ')')
                    .replace('_', ' ').casefold().split()).strip()


@lru_cache(maxsize=4)
def _preset_names(path, mtime, size):
    with open(path, encoding='utf-8-sig') as file:
        data = json.load(file)
    rows = data.get('characters', {})
    if not isinstance(rows, dict):
        raise ValueError('characters must be an object')
    return frozenset(_key(name) for name in rows)


@lru_cache(maxsize=4)
def _catalog_names(dictionary, edits, dictionary_sig, edits_sig):
    return frozenset(_key(value) for row in load_character_catalog(dictionary, edits)
                     for value in (row['tag'], row['base_tag'], *row['aliases'], *row['copyright']))


def _signature(path):
    info = path.stat() if path.is_file() else None
    return (info.st_mtime_ns, info.st_size) if info else None


def _identity_names(settings):
    names = set()
    dictionary = settings.character_dictionary_path
    if dictionary.is_file():
        edits = settings.character_dictionary_edits_path
        names.update(_catalog_names(dictionary, edits, _signature(dictionary), _signature(edits)))
    path = settings.preset_path
    if path.is_file():
        info = path.stat()
        names.update(_preset_names(str(path), info.st_mtime_ns, info.st_size))
    return names


# Whole-tag forms: do not remove actions such as holding hair, closed eyes,
# looking into eyes, a hair ornament, or an animal in the background.
_HAIR = re.compile(r'(?:(?:very |light |dark |pale |gradient |multicolored |two-tone )*(?:short|medium|long|black|white|grey|gray|silver|red|pink|orange|yellow|blonde?|brown|green|aqua|blue|purple|violet|lavender|platinum|teal|cyan|rainbow|straight|wavy|curly|messy|fluffy|spiked|spiky|swept-back|drill|ringlet|absurdly long|very long)|multicolored|two-tone|gradient) hair')
_EYES = re.compile(r'(?:(?:light |dark |pale )?(?:black|white|grey|gray|silver|red|pink|orange|yellow|gold|golden|brown|green|aqua|blue|purple|violet|lavender|teal|cyan)|multicolored|two-tone) eyes')
_SKIN = re.compile(r'(?:dark|light|pale|fair|tan|tanned|brown|black|white|blue|green|grey|gray) skin')
_FEATURES = re.compile(r'(?:(?:animal|fox|cat|wolf|rabbit|dog|bear|horse|elf|pointy|pointed|floppy) ears|(?:fox|cat|wolf|rabbit|dog|animal|fluffy|multiple|long) tails?|(?:large|small|medium|huge) breasts|flat chest|(?:long|short|twin|side|braided|high|low)? ?(?:ponytail|twintails|braids?)|(?:hair over one eye|hair between eyes|sidelocks|ahoge|bangs|blunt bangs|parted bangs|asymmetrical bangs|freckles|mole|mole under eye|heterochromia|slit pupils|furry|kemonomimi|horns|antlers|halo|wings|tail))')


def reusable_text(settings, text, *, excluded=()):
    """Filter identity tags without changing the generation text or tag order."""
    try:
        names = _identity_names(settings) | {_key(part) for value in excluded for part in _parts(str(value))}
    except (OSError, ValueError, TypeError) as exc:
        raise RepositoryError('角色词典无法读取，暂不能核对收藏内容') from exc

    def clean(tag):
        # Preserve weighted groups while filtering their individual children.
        if tag.startswith(('(', '[')) and tag.endswith(')' if tag[0] == '(' else ']'):
            inner = tag[1:-1]
            weight = re.search(r':\s*[-+]?\d+(?:\.\d+)?\s*$', inner)
            suffix = inner[weight.start():] if weight else ''
            body = inner[:weight.start()] if weight else inner
            children = [value for part in _parts(body) if (value := clean(part))]
            return tag[0] + ', '.join(children) + suffix + tag[-1] if children else ''
        value = _key(tag)
        if (value in names or value.startswith(('character:', 'copyright:', '<lora:', '<lyco:'))
                or _HAIR.fullmatch(value) or _EYES.fullmatch(value)
                or _SKIN.fullmatch(value) or _FEATURES.fullmatch(value)):
            return ''
        return tag

    return ', '.join(value for part in _parts(str(text)) if (value := clean(part)))


def favorite_task_snapshot(settings, job, index=0, load_job=None, _seen=()):
    """Resolve a specific output to its editable base, including edited remakes."""
    identifier = str(job.get('job_id', ''))
    if identifier in _seen or len(_seen) >= 8:
        raise RepositoryError('任务来源链循环或过长')
    data = job.get('input') or {}
    # Reuse the actual reader's index/ancestry validation, but never its positive.
    try:
        actual = image_prompt_snapshot(job, index, load_job)
    except (TypeError, ValueError) as exc:
        raise RepositoryError(str(exc)) from exc
    kind = (job.get('workflow') or {}).get('type', job.get('workflow_type', ''))
    if kind == 'seedvr2_refine_v1':
        enhance = job.get('enhance') or {}
        parent = enhance.get('hq_detail_job_id') or enhance.get('hq_base_job_id') or job.get('parent_job_id')
        original = load_job(str(parent)) if parent and load_job else None
        if original:
            return favorite_task_snapshot(settings, original, int(data.get('source_image_index', index)),
                                          load_job, (*_seen, identifier))
        return dict(available=False, kind='reusable', positive='')

    entries = data.get('source_entries') or []
    # HQ detail and exact-input refine may carry their parent's compiled text
    # in input.prompt. Follow the selected parent's base only on an exact match;
    # a newly supplied refine prompt remains the new editable content.
    if (not entries and kind in {'refine_existing_v1', 'detail_repair_anima_v1'}
            and job.get('parent_job_id') and load_job):
        original = load_job(str(job['parent_job_id']))
        if original:
            parent_outputs = (original.get('result') or {}).get('assets') or []
            if 'source_image_index' not in data and len(parent_outputs) > 1:
                raise RepositoryError('旧精修任务缺少来源图片序号，不能猜测收藏内容')
            parent_index = int(data.get('source_image_index', index))
            parent_actual = image_prompt_snapshot(original, parent_index, load_job)
            if str(data.get('prompt') or '').strip() == parent_actual.get('positive'):
                return favorite_task_snapshot(settings, original, parent_index, load_job, (*_seen, identifier))
    if len(entries) > 1 and index >= len(entries):
        raise RepositoryError('逐图来源数量不一致，不能套用其他图片')
    source = entries[0] if len(entries) == 1 else (entries[index] if entries else {})
    raw_batch = data.get('raw_batch_prompts') or []
    if raw_batch:
        if index >= len(raw_batch):
            raise RepositoryError('逐图基础提示词数量不一致')
        base = str(raw_batch[index])
    elif source.get('prompt'):
        # Remakes update this frozen entry, with user_addition already merged.
        base = full_prompt(source['prompt'], source.get('user_addition', ''))
    elif data.get('prompt') and not data.get('batch_prompts'):
        base = str(data['prompt'])
    else:
        # Compiled-only old tasks cannot reliably distinguish identity from scene.
        return dict(available=False, kind='reusable', positive='')
    presets = data.get('preset_snapshot') or {}
    character = presets.get('character') or {}
    excluded = [character.get('prompt', '')] if isinstance(character, dict) else []
    options = data.get('generation_options') or {}
    excluded.append(options.get('character', ''))
    positive = reusable_text(settings, base, excluded=excluded)
    return {**actual, 'available': bool(positive), 'kind': 'reusable',
            'positive': positive, 'source_prompt': positive, 'user_addition': '',
            'stage': '可复用提示词（排除角色身份、外貌与预设）',
            'require_safety': actual.get('kind') == 'legacy_source',
            'safety_code': actual.get('safety_code') or ('' if actual.get('kind') == 'legacy_source' else 'S')}
