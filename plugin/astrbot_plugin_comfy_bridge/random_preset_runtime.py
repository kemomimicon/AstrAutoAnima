"""Choose one usable preset, distinct from chaos and palette generation."""
import copy
import hashlib
import json
import math
import re
import secrets
import time
from pathlib import Path

from .workflow_runtime import WorkflowError


def is_random_style(value):
    return str(value) == '随机模式' or str(value).startswith('__hub_random_')


def qq_personal_keys(data_root, qq):
    """Only an unambiguous enabled local QQ account can expose its own slots."""
    if not re.fullmatch(r'[1-9][0-9]{4,14}', str(qq)):
        return set()
    root = Path(data_root) / 'hub_state'
    try:
        registry = root / 'lite_users.json'
        personal = root / 'personal_styles.json'
        if registry.is_symlink() or personal.is_symlink():
            return set()
        rows = json.loads(registry.read_text('utf-8-sig')).get('users', [])
        matches = [r for r in rows if isinstance(r, dict) and r.get('enabled', True) and str(r.get('qq')) == str(qq)]
        if len(matches) != 1:
            return set()
        subject = str(matches[0].get('id', ''))
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', subject):
            return set()
        slots = json.loads(personal.read_text('utf-8-sig')).get('users', {}).get(subject, {})
        digest = hashlib.sha256(subject.encode()).hexdigest()[:14]
        return {f'__hub_personal_{digest}_{int(slot)}' for slot, value in slots.items()
                if str(slot).isdigit() and isinstance(value, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


def choose_random_style(styles, requested, data_root, lora_root, *, qq=''):
    permitted = set()
    if requested == '随机模式':
        permitted = qq_personal_keys(data_root, qq)
    if requested != '随机模式':
        token = str(requested).removeprefix('__hub_random_')
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise WorkflowError('随机画风凭据无效')
        path = Path(data_root) / 'hub_state' / 'random_styles' / (token + '.json')
        if not path.is_file() or path.is_symlink():
            raise WorkflowError('随机画风凭据不存在或已过期')
        ticket = json.loads(path.read_text(encoding='utf-8'))
        if float(ticket.get('expires_at', 0)) <= time.time():
            raise WorkflowError('随机画风凭据已过期，请重新提交')
        permitted = set(ticket.get('personal_keys', []))
    root = Path(lora_root).resolve()
    candidates = []
    for name, preset in styles.items():
        if not isinstance(preset, dict) or preset.get('enabled', True) is False:
            continue
        if (name.startswith('__') or preset.get('hidden')) and name not in permitted:
            continue
        loras = preset.get('loras', [])
        if not isinstance(loras, list) or (not loras and not str(preset.get('prompt', '')).strip()):
            continue
        valid = True
        for item in loras:
            if not isinstance(item, dict):
                valid = False
                break
            path = (root / str(item.get('name', '')).replace('\\', '/')).resolve()
            weights = [item.get('strength_model', 1), item.get('strength_clip', 1)]
            if (not path.is_relative_to(root) or not path.is_file() or
                    any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) for w in weights)):
                valid = False
                break
        if valid:
            candidates.append((name, preset))
    if not candidates:
        raise WorkflowError('没有可用的随机画风预设，请检查预设和 LoRA 文件')
    name, preset = secrets.choice(candidates)
    return name, copy.deepcopy(preset)
