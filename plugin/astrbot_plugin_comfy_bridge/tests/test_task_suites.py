import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from astrbot_plugin_comfy_bridge.task_suite_runtime import row_options, execute_suite, suite_token, load_run, bind_qq_suite
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


def run_data():
    row = {'character': 'alice', 'style': 'watercolor', 'style_snapshot': {'prompt': 'watercolor'}, 'character_snapshot': None}
    return dict(id='suite', name='比较', rows=[row, {**row, 'character': 'bob'}], rows_status=['queued', 'queued'], expires_at=time.time()+100)


def test_seed_and_snapshot_options():
    run = run_data()
    source = {'_copy_character': {'prompt': 'old'}, '_restore_lora_stack': [], 'character_variant': 'old', '_fixed_seed': 42, 'fixed_seed': True}
    opts = row_options(source, run['rows'][0], run, 0)
    assert opts['_fixed_seed'] == 42
    assert '_copy_character' not in opts and '_restore_lora_stack' not in opts
    opts['_copy_style']['prompt'] = 'changed'
    assert run['rows'][0]['style_snapshot']['prompt'] == 'watercolor'
    assert source['character_variant'] == 'old'


@pytest.mark.parametrize('token', ['../bad', 'x', 'a'*33])
def test_invalid_token(token):
    with pytest.raises(WorkflowError):
        suite_token({'style': '__hub_suite_' + token})


def test_same_prompt_sequential_failure_and_cancel(tmp_path):
    async def run_test(cancel):
        run = run_data()
        token = ('a' if cancel else 'b') * 32
        root = tmp_path / 'hub_state/task_suite_runs'
        root.mkdir(parents=True, exist_ok=True)
        path = root / f'{token}.json'
        path.write_text(json.dumps(run), encoding='utf-8')
        calls = []
        async def deliver(event, **kwargs):
            calls.append(kwargs)
            if cancel:
                path.with_suffix('.cancel').touch()
            return False if len(calls) == 1 else True
        async def send(message):
            pass
        plugin = SimpleNamespace(_character_dictionary_path=lambda: tmp_path / 'dictionary.json', _deliver_generation=deliver)
        event = SimpleNamespace(send=send, plain_result=lambda v: v)
        await execute_suite(plugin, event, 'shared prompt', {'style': '__hub_suite_' + token}, {})
        result = json.loads(path.read_text())
        assert all(c['prompt'] == 'shared prompt' for c in calls)
        assert result['rows_status'] == (['failed', 'cancelled'] if cancel else ['failed', 'succeeded'])
        with pytest.raises(WorkflowError, match='重复'):
            await execute_suite(plugin, event, 'shared prompt', {'style': '__hub_suite_' + token}, {})
    asyncio.run(run_test(False))
    asyncio.run(run_test(True))


def test_expired_ticket(tmp_path):
    root = tmp_path / 'hub_state/task_suite_runs'
    root.mkdir(parents=True)
    (root / ('a'*32 + '.json')).write_text(json.dumps({**run_data(), 'expires_at': 0}))
    with pytest.raises(WorkflowError):
        load_run(tmp_path, 'a'*32)


def test_qq_personal_suite_requires_unique_owner(tmp_path):
    root = tmp_path / 'hub_state'
    root.mkdir()
    (root / 'lite_users.json').write_text(json.dumps({'users': [{'id': 'owner', 'qq': '123456', 'enabled': True}]}))
    (root / 'task_suites.json').write_text(json.dumps({'items': {'suite': {'id': 'suite', 'name': '套组', 'owner': 'owner', 'scope': 'personal', 'rows': [{'character_kind': 'preset', 'character': 'c', 'style_kind': 'global', 'style': 's'}]}}}), encoding='utf-8')
    presets = tmp_path / 'presets.json'
    presets.write_text(json.dumps({'characters': {'c': {'prompt': 'alice'}}, 'styles': {'s': {'prompt': 'watercolor'}}}))
    plugin = SimpleNamespace(_character_dictionary_path=lambda: tmp_path/'dictionary.json', _preset_path=lambda: presets)
    event = SimpleNamespace(get_platform_name=lambda: 'aiocqhttp', get_sender_id=lambda: '999999')
    with pytest.raises(WorkflowError, match='无权'):
        bind_qq_suite(plugin, event, {'task_suite': '套组'})
    event.get_sender_id = lambda: '123456'
    options = bind_qq_suite(plugin, event, {'task_suite': '套组'})
    _, run = load_run(tmp_path, suite_token(options))
    assert run['rows'][0]['character_snapshot']['prompt'] == 'alice'
