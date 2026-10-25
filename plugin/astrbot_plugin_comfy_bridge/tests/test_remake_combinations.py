"""Cross-feature replay regression tests, without live services or GPU jobs."""
import asyncio
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test_remake_inheritance import bind, parent
from astrbot_plugin_comfy_bridge.camera_runtime import compile_camera_options
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives
from astrbot_plugin_comfy_bridge.replay_runtime import copy_context
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


@pytest.mark.parametrize('flag', [True, False])
def test_modified_hq_honors_explicit_upscale(tmp_path, flag):
    async def run():
        job = parent()
        job['enhance'] = {'hq_replay_full_chain': True, 'detail_upscale': True}
        job['input']['generation_options'].update(detail_hands=True, detail_upscale=True)
        owner = SimpleNamespace(config={}, _deliver_generation=AsyncMock(),
                                _character_dictionary_path=lambda: tmp_path / 'dict.json')
        event = SimpleNamespace(send=AsyncMock(), plain_result=lambda text: text)
        await bind('_remake_modified', owner)(
            event, job, 0, '比例=16:9 修复后放大=' + ('开启' if flag else '关闭'), 0)
        kwargs = owner._deliver_generation.await_args.kwargs
        assert kwargs['workflow_type'] == 'hq_txt2img_anima_v1'
        assert kwargs['options']['detail_upscale'] is flag
        assert kwargs['options']['_fixed_seed'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('flag', [True, False])
def test_camera_auxiliary_snapshot_never_duplicates_or_resists_disable(flag):
    job = parent()
    base = {'name': 'art.safetensors', 'strength_model': 1, 'strength_clip': 1}
    camera = {'name': 'camera.safetensors', 'strength_model': .65, 'strength_clip': 0.0}
    job['input']['generation_options'].update(camera_pitch='extreme_low', camera_extreme_lora=True)
    job['input']['preset_snapshot'] = {'style': {'loras': [base, camera], 'prompt': 'art'}}
    before = copy.deepcopy(job)
    _, options = copy_context(job, 0, {'camera_extreme_lora': flag}, camera_lora_name='camera.safetensors')
    assert options['camera_extreme_lora'] is flag
    assert options['_copy_style']['loras'] == [base]
    plan = compile_camera_options(options, extreme_lora_name='camera.safetensors')
    applied = options['_copy_style']['loras'] + ([plan.lora] if plan.lora else [])
    assert sum(row['name'] == 'camera.safetensors' for row in applied) == int(flag)
    assert job == before
    # New-style snapshots contain only the user preset, so no heuristic is needed.
    job['input']['preset_snapshot'] = {'style': {'loras': [base], 'prompt': 'art'},
                                     'camera_auxiliary_embedded': False}
    _, options = copy_context(job, 0, {'camera_extreme_lora': flag})
    assert options['_copy_style']['loras'] == [base]


def test_legacy_auxiliary_does_not_guess_when_config_changed():
    job = parent()
    job['input']['generation_options'].update(camera_pitch='extreme_low', camera_extreme_lora=True)
    job['input']['preset_snapshot'] = {'style': {'loras': [
        {'name': 'old-camera.safetensors', 'strength_model': .65, 'strength_clip': 0.0}]}}
    with pytest.raises(WorkflowError, match='来源无法确认'):
        copy_context(job, 0, {'camera_extreme_lora': False}, camera_lora_name='new-camera.safetensors')
    # Explicitly picking a different style remains an available recovery route.
    _, options = copy_context(job, 0, {'style': 'new', 'camera_extreme_lora': False})
    assert '_copy_style' not in options and options['camera_extreme_lora'] is False


def test_false_zero_and_inherited_upscale_are_not_lost():
    job = parent()
    job['input']['generation_options'].update(detail_upscale=True)
    _, options = copy_context(job, 0, {})
    assert options['detail_upscale'] is True
    _, overrides = parse_generation_directives('角色模型=0 角色clip=0 画风倍率=0 修手=关闭 修复后放大=关闭 极限辅助=关闭')
    _, options = copy_context(job, 0, overrides)
    for key in ('character_model', 'character_clip', 'style_scale'):
        assert options[key] == 0
    for key in ('detail_hands', 'detail_upscale', 'camera_extreme_lora'):
        assert options[key] is False


def test_modified_text_snapshot_preserves_origin_but_favorites_use_new_text(tmp_path):
    async def run():
        job = parent()
        job['input']['source_entries'] = [{'id': 'G-1', 'prompt': 'red bicycle, stone wall',
            'user_addition': 'rainy street', 'safety_level': 'normal'}]
        owner = SimpleNamespace(config={}, _deliver_generation=AsyncMock(), _safety_input=AsyncMock(),
            _character_dictionary_path=lambda: tmp_path / 'dict.json', _llm_max_tokens=lambda: 1000,
            context=SimpleNamespace(llm_generate=AsyncMock(return_value=SimpleNamespace(
                completion_text='{"remove":[0],"add":["blue bicycle"]}'))))
        event = SimpleNamespace(send=AsyncMock(), plain_result=lambda text: text)
        method = bind('_remake_modified', owner, current_text_provider_id=AsyncMock(return_value='text'))
        await method(event, job, 0, 'blue bicycle', 1)
        kwargs = owner._deliver_generation.await_args.kwargs
        entry = kwargs['options']['_source_entries'][0]
        assert entry['id'] == 'G-1' and entry['safety_level'] == 'normal'
        assert entry['prompt'] == kwargs['prompt'] == 'stone wall, rainy street, blue bicycle'
        assert entry['user_addition'] == ''
        assert entry['original_prompt'] == 'red bicycle, stone wall'
        assert entry['original_user_addition'] == 'rainy street'
        assert entry['edit_request'] == 'blue bicycle'
        assert job['input']['source_entries'][0]['user_addition'] == 'rainy street'
    asyncio.run(run())


@pytest.mark.parametrize('fail_delivery', [True, False])
def test_generated_replay_remains_completed_when_delivery_fails(tmp_path, fail_delivery):
    @asynccontextmanager
    async def slot(*args, **kwargs):
        yield object()
    async def run():
        job, snapshots = parent(), []
        store = SimpleNamespace(create_job=Mock(return_value={'job_id': 'child', 'result': {}}),
            register_asset=Mock(return_value={'asset_id': 'image'}),
            save_job=lambda item: snapshots.append(copy.deepcopy(item)))
        owner = SimpleNamespace(_job_store=lambda: store, _safety_guard=Mock(),
            _quoted_job=AsyncMock(return_value=(job, 0)),
            _safety_policy=lambda event=None: SimpleNamespace(fingerprint='same'),
            _safety_input=AsyncMock(), _safety_applies=lambda e: False,
            _event_source=lambda e: {}, _generation_slot=slot,
            _timeout_seconds=lambda: 1, _submit_workflow=AsyncMock(return_value='id'),
            _wait_for_history=AsyncMock(return_value={}),
            _download_images=AsyncMock(return_value=[tmp_path / 'image.png']),
            _character_dictionary_path=lambda: tmp_path / 'dict.json',
            _safety_outputs=AsyncMock(side_effect=lambda e, paths: paths),
            _remake_modified=AsyncMock(), config={})
        event = SimpleNamespace(message_str='/aremake', should_call_llm=Mock(), stop_event=Mock(),
                                plain_result=lambda text: text, send=AsyncMock())
        delivery = AsyncMock(side_effect=TimeoutError('sendMsg timeout') if fail_delivery else None)
        method = bind('aremake', owner, logger=Mock(),
            aiohttp=SimpleNamespace(ClientTimeout=lambda **kw: None, ClientSession=slot),
            extract_output_images=lambda r: [{}], send_tracked_image=delivery)
        await method(event)
        assert snapshots[-1]['status'] == 'completed'
        assert snapshots[-1]['result']['assets'] == ['image']
        assert snapshots[-1]['result']['delivery']['status'] == ('unconfirmed' if fail_delivery else 'sent')
        delivery.assert_awaited_once()
        owner._submit_workflow.assert_awaited_once()
    asyncio.run(run())
