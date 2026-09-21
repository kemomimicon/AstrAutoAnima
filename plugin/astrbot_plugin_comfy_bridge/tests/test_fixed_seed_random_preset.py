import copy
import json
import time

import pytest

from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives
from astrbot_plugin_comfy_bridge.replay_runtime import replay_workflow
from astrbot_plugin_comfy_bridge.random_preset_runtime import choose_random_style, qq_personal_keys
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


def test_seed_flag_between_ratio_and_adjustment():
    text, options = parse_generation_directives('角色=梅娅 画风=云亭 比例=2:3 固定种子 把背景改成雨夜')
    assert text == '把背景改成雨夜'
    assert options['fixed_seed'] is True
    assert options['ratio'] == '2:3'
    text, options = parse_generation_directives('比例=2:3 图片上写固定种子')
    assert 'fixed_seed' not in options
    assert text == '图片上写固定种子'


def test_preserve_each_stage_seed_without_mutating_parent():
    job = {'sampling': {'seed': 42}, 'workflow_snapshot': {
        '1': {'inputs': {'seed': 42}}, '2': {'inputs': {'noise_seed': 52}}}}
    original = copy.deepcopy(job)
    graph, seed, _ = replay_workflow(job, 0, fixed_seed=True)
    assert seed == 42 and graph['2']['inputs']['noise_seed'] == 52
    assert original == job
    graph, seed, _ = replay_workflow(job, 0)
    assert seed != 42
    job['input'] = {'batch_prompts': ['a', 'b']}
    with pytest.raises(WorkflowError, match='合批'):
        replay_workflow(job, 1, fixed_seed=True)


def test_random_skips_stale_hidden_and_unauthorized(tmp_path):
    models = tmp_path / 'models'
    models.mkdir()
    (models / 'ok.safetensors').write_bytes(b'test')
    styles = {
        'public': {'loras': [{'name': 'ok.safetensors'}], 'prompt': 'art'},
        'stale': {'loras': [{'name': 'missing.safetensors'}]},
        '__hub_personal_owner_1': {'hidden': True, 'prompt': 'private'},
        '__hub_trial_any': {'prompt': 'temporary'},
    }
    for _ in range(8):
        name, preset = choose_random_style(styles, '随机模式', tmp_path, models)
        assert name == 'public'
        preset['prompt'] = 'changed'
    assert styles['public']['prompt'] == 'art'
    token = 'a' * 32
    ticket = tmp_path / 'hub_state' / 'random_styles' / (token + '.json')
    ticket.parent.mkdir(parents=True)
    ticket.write_text(json.dumps({'expires_at': time.time() + 100,
                                 'personal_keys': ['__hub_personal_owner_1']}))
    styles.pop('public')
    assert choose_random_style(styles, '__hub_random_' + token, tmp_path, models)[0] == '__hub_personal_owner_1'
    with pytest.raises(WorkflowError):
        choose_random_style(styles, '随机模式', tmp_path, models)


def test_random_blocks_outside_model_root(tmp_path):
    (tmp_path / 'outside').write_bytes(b'test')
    (tmp_path / 'models').mkdir()
    with pytest.raises(WorkflowError):
        choose_random_style({'unsafe': {'loras': [{'name': '../outside'}]}}, '随机模式', tmp_path, tmp_path / 'models')


def test_qq_personal_ownership_and_ambiguous_binding(tmp_path):
    import hashlib
    root = tmp_path / 'hub_state'
    root.mkdir()
    rows = [{'id': 'mine', 'qq': '123456'}, {'id': 'other', 'qq': '999999'}]
    (root / 'lite_users.json').write_text(json.dumps({'users': rows}))
    (root / 'personal_styles.json').write_text(json.dumps({'users': {'mine': {'1': {}}, 'other': {'2': {}}}}))
    digest = hashlib.sha256(b'mine').hexdigest()[:14]
    assert qq_personal_keys(tmp_path, '123456') == {f'__hub_personal_{digest}_1'}
    rows.append({'id': 'duplicate', 'qq': '123456'})
    (root / 'lite_users.json').write_text(json.dumps({'users': rows}))
    assert not qq_personal_keys(tmp_path, '123456')


def test_native_seedvr2_honors_fixed_seed_in_modified_hq():
    import ast
    import secrets
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text('utf-8'))
    assignment = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                      and isinstance(n.value, ast.IfExp)
                      and any(isinstance(t, ast.Tuple) and [getattr(e, 'id', '') for e in t.elts] == ['workflow', 'seed'] for t in n.targets))
    _, seed = eval(compile(ast.Expression(assignment.value), 'native-seed', 'eval'),
                   {'workflow_type': 'seedvr2_refine_v1', 'template': {}, 'copy': copy,
                    'secrets': secrets, 'options': {'_fixed_seed': 12345},
                    'self': SimpleNamespace(config={'randomize_seed': True})})
    assert seed == 12345
