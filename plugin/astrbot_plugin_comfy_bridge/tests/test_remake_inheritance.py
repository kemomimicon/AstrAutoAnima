"""Neutral fixtures: assert final submitted graphs, not only parsed options."""
import ast
import copy
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_comfy_bridge.replay_runtime import (
    apply_prompt_patch, prompt_parts, copy_context, replay_workflow,
)
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives
from astrbot_plugin_comfy_bridge.workflow_runtime import (
    WorkflowError, prepare_workflow, extract_command_body,
)
from astrbot_plugin_comfy_bridge.safety_runtime import positive_texts
from astrbot_plugin_comfy_bridge.delivery_runtime import qq_official_reply_ids, qq_official_quote_markers, log_qq_official_quote_diagnostic


def parent():
    prompt = "red bicycle, stone wall, rainy street"
    return {
        "job_id": "parent", "workflow": {"type": "quick_txt2img_v1", "version": "1"},
        "input": {"prompt": prompt, "compiled_prompt": prompt,
                  "generation_options": {"sampler_steps": 12, "sampler_cfg": 3}},
        "sampling": {"seed": 1610535837733140667, "steps": 40, "cfg": 9.0,
                     "sampler_name": "dpmpp_2m", "scheduler": "normal", "denoise": 1.0},
        "workflow_snapshot": {
            "11": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt}},
            "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "blur"}},
            "19": {"class_type": "KSampler", "inputs": {
                "positive": ["11", 0], "negative": ["12", 0],
                "seed": 1610535837733140667, "steps": 40, "cfg": 9.0,
                "sampler_name": "dpmpp_2m", "scheduler": "normal", "denoise": 1.0}},
            "28": {"class_type": "EmptyLatentImage", "inputs": {
                "width": 1024, "height": 1536, "batch_size": 1}},
        },
    }


def bind(name, owner, **extra):
    tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text("utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ComfyWorkflowBridge")
    method = next(n for n in cls.body if getattr(n, "name", "") == name)
    method.decorator_list = []
    namespace = dict(globals(), __package__="astrbot_plugin_comfy_bridge",
                     AstrMessageEvent=object, compile_prompt=lambda text, *a, **kw: text)
    namespace.update(extra)
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<actual-method>", "exec"), namespace)
    return MethodType(namespace[name], owner)


@pytest.mark.parametrize("directive", ["", "步数=35 CFG=7", "采样器=euler"])
def test_actual_sampler_method_and_workflow_preserve_recorded_values(directive):
    job = parent()
    _, explicit = parse_generation_directives(directive)
    prompt, options = copy_context(job, 0, explicit)
    # Even if the administrator changed the preset mapping, recorded name wins.
    owner = SimpleNamespace(config={"default_sampler_name": "er_sde", "dpm_sampler_name": "heun"})
    _, overrides = bind("_sampler_overrides", owner)(options)
    graph, seed = prepare_workflow(
        job["workflow_snapshot"], prompt=prompt, positive_node_id="11",
        sampler_node_id="19", randomize_seed=False, fixed_seed=job["sampling"]["seed"],
        sampler_overrides=overrides,
    )
    values = graph["19"]["inputs"]
    assert values["steps"] == (35 if "步数" in directive else 40)
    assert values["cfg"] == (7 if "CFG" in directive else 9)
    assert values["sampler_name"] == ("euler" if "采样器" in directive else "dpmpp_2m")
    assert values["scheduler"] == "normal"
    assert values["denoise"] == 1
    assert seed == job["sampling"]["seed"]
    assert job == parent()


def test_prompt_patch_keeps_unmodified_parts_and_handles_weights():
    original = "red bicycle, (stone wall, moss:1.2), rainy street"
    assert prompt_parts(original) == ["red bicycle", "(stone wall, moss:1.2)", "rainy street"]
    escaped = "bicycle" + chr(92) + ", red"
    assert prompt_parts(escaped + ", street") == [escaped, "street"]
    assert apply_prompt_patch(original, {"remove": [0], "add": ["blue bicycle"]}) == (
        "(stone wall, moss:1.2), rainy street, blue bicycle")
    assert apply_prompt_patch(original, {"remove": [], "add": []}) == original


@pytest.mark.parametrize("patch", [
    {"prompt": "blue bicycle"},
    {"remove": [0, 1], "add": ["blue bicycle"]},
    {"remove": [10], "add": []},
    {"remove": [True], "add": []},
    {"remove": [0, 0], "add": []},
    {"remove": [], "add": "blue bicycle"},
    {"remove": [], "add": [""]},
])
def test_bad_or_wholesale_edits_fail_instead_of_losing_scene(patch):
    with pytest.raises(WorkflowError):
        apply_prompt_patch(parent()["input"]["prompt"], patch)


def test_modified_remake_keeps_existing_input_and_llm_contract(tmp_path):
    import asyncio
    async def run():
        model = AsyncMock(return_value=SimpleNamespace(
            completion_text='{"remove":[0],"add":["blue bicycle"]}'))
        owner = SimpleNamespace(config={}, context=SimpleNamespace(llm_generate=model),
                                _llm_max_tokens=lambda: 1000,
                                _safety_input=AsyncMock(), _deliver_generation=AsyncMock(),
                                _character_dictionary_path=lambda: tmp_path / "dict.json")
        event = SimpleNamespace(send=AsyncMock(), plain_result=lambda text: text)
        provider = AsyncMock(return_value="configured")
        method = bind("_remake_modified", owner, current_text_provider_id=provider)
        await method(event, parent(), 0, "固定种子 blue bicycle", 123)
        kwargs = owner._deliver_generation.await_args.kwargs
        assert kwargs["prompt"] == "stone wall, rainy street, blue bicycle"
        assert kwargs["options"]["sampler_steps"] == 40
        assert kwargs["options"]["sampler_cfg"] == 9
        assert kwargs["options"]["_fixed_seed"] == 123
        model.assert_awaited_once()
        owner._deliver_generation.reset_mock()
        model.return_value = SimpleNamespace(completion_text='{"prompt":"blue bicycle"}')
        with pytest.raises(WorkflowError, match="原提示词未被覆盖"):
            await method(event, parent(), 0, "blue bicycle", 123)
        owner._deliver_generation.assert_not_awaited()
        provider.return_value = ""
        with pytest.raises(WorkflowError, match="文本Provider"):
            await method(event, parent(), 0, "blue bicycle", 123)
        owner._deliver_generation.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("fixed", [True, False])
def test_unmodified_aremake_final_submission_keeps_snapshot_and_prompt(tmp_path, fixed):
    import asyncio
    @asynccontextmanager
    async def slot(*args, **kwargs):
        yield object()
    async def run():
        job = parent()
        store = SimpleNamespace(
            create_job=Mock(return_value={"job_id": "child", "result": {}}),
            register_asset=Mock(return_value={"asset_id": "image"}), save_job=Mock())
        owner = SimpleNamespace(
            _job_store=lambda: store, _safety_guard=Mock(),
            _quoted_job=AsyncMock(return_value=(job, 0)),
            _safety_policy=lambda event=None: SimpleNamespace(fingerprint="same"),
            _safety_input=AsyncMock(), _safety_applies=lambda e: False,
            _event_source=lambda e: {}, _generation_slot=slot,
            _timeout_seconds=lambda: 1, _submit_workflow=AsyncMock(return_value="id"),
            _wait_for_history=AsyncMock(return_value={}),
            _download_images=AsyncMock(return_value=[tmp_path / "image.png"]),
            _character_dictionary_path=lambda: tmp_path / "dict.json",
            _safety_outputs=AsyncMock(side_effect=lambda e, paths: paths),
            _remake_modified=AsyncMock(), config={})
        event = SimpleNamespace(
            message_str="/aremake " + ("固定种子 " if fixed else "") + "",
            should_call_llm=Mock(), stop_event=Mock(), plain_result=lambda x: x, send=AsyncMock())
        logger = Mock()
        method = bind("aremake", owner, logger=logger,
                      aiohttp=SimpleNamespace(ClientTimeout=lambda **kw: None, ClientSession=slot),
                      extract_output_images=lambda r: [{}], send_tracked_image=AsyncMock())
        await method(event)
        logger.exception.assert_not_called()
        owner._remake_modified.assert_not_awaited()
        graph = owner._submit_workflow.await_args.args[1]
        expected = copy.deepcopy(job["workflow_snapshot"])
        if fixed:
            assert graph == expected
        else:
            assert graph["19"]["inputs"]["seed"] != job["sampling"]["seed"]
            expected["19"]["inputs"]["seed"] = graph["19"]["inputs"]["seed"]
            assert graph == expected
        input_data = store.create_job.call_args.kwargs["input_data"]
        assert input_data["compiled_prompt"] == expected["11"]["inputs"]["text"]
        assert store.save_job.call_args.args[0]["workflow_snapshot"] == graph
    asyncio.run(run())
