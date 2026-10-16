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
    append_snapshot_prompt, copy_context, replay_workflow,
)
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives
from astrbot_plugin_comfy_bridge.workflow_runtime import (
    WorkflowError, prepare_workflow, extract_command_body,
)
from astrbot_plugin_comfy_bridge.safety_runtime import positive_texts


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


def test_append_snapshot_is_literal_and_repeatable():
    job = parent()
    graph, _, _ = replay_workflow(job, 0, fixed_seed=True)
    changed, graph = append_snapshot_prompt(job, graph, 0, "blue bicycle")
    assert graph["11"]["inputs"]["text"] == job["input"]["prompt"] + ", blue bicycle"
    assert graph["12"] == job["workflow_snapshot"]["12"]
    assert graph["19"] == job["workflow_snapshot"]["19"]
    assert graph["28"] == job["workflow_snapshot"]["28"]
    changed["workflow_snapshot"] = graph
    child, again = append_snapshot_prompt(changed, graph, 0, "sunset")
    assert child["input"]["prompt"].endswith(", blue bicycle, sunset")
    assert again["11"]["inputs"]["text"] == child["input"]["compiled_prompt"]
    assert job == parent()


def test_batch_selected_image_and_unknown_or_shared_nodes_fail_closed():
    job = parent()
    job["input"].update(batch_prompts=["first bicycle", "second bicycle"],
                        raw_batch_prompts=["first bicycle", "second bicycle"])
    job["workflow_snapshot"]["11"] = {"class_type": "AnimaPromptBatchEncode",
                                      "inputs": {"prompts_json": '["first bicycle", "second bicycle"]'}}
    graph, _, output_index = replay_workflow(job, 1)
    changed, graph = append_snapshot_prompt(job, graph, 1, "rain")
    assert json.loads(graph["11"]["inputs"]["prompts_json"]) == ["second bicycle, rain"]
    assert changed["input"]["raw_batch_prompts"] == ["first bicycle", "second bicycle, rain"]
    assert output_index == 0
    with pytest.raises(WorkflowError):
        replay_workflow(job, 1, fixed_seed=True)
    graph = parent()["workflow_snapshot"]
    graph["19"]["inputs"]["negative"] = ["11", 0]
    with pytest.raises(WorkflowError, match="共用"):
        append_snapshot_prompt(parent(), graph, 0, "rain")
    graph["11"]["class_type"] = "UnknownEncoder"
    with pytest.raises(WorkflowError, match="未支持"):
        append_snapshot_prompt(parent(), graph, 0, "rain")


def test_modified_default_append_needs_no_llm_and_explicit_ai_does(tmp_path):
    import asyncio
    async def run():
        owner = SimpleNamespace(config={}, context=SimpleNamespace(llm_generate=AsyncMock()),
                                _safety_input=AsyncMock(), _deliver_generation=AsyncMock(),
                                _character_dictionary_path=lambda: tmp_path / "dict.json")
        event = SimpleNamespace(send=AsyncMock(), plain_result=lambda text: text)
        method = bind("_remake_modified", owner, current_text_provider_id=AsyncMock(return_value=""))
        await method(event, parent(), 0, "固定种子 blue bicycle", 123)
        kwargs = owner._deliver_generation.await_args.kwargs
        assert kwargs["prompt"] == parent()["input"]["prompt"] + ", blue bicycle"
        assert kwargs["options"]["sampler_steps"] == 40
        assert kwargs["options"]["sampler_cfg"] == 9
        assert kwargs["options"]["_fixed_seed"] == 123
        owner.context.llm_generate.assert_not_awaited()
        with pytest.raises(WorkflowError, match="文本Provider"):
            await method(event, parent(), 0, "AI改写：blue bicycle", 123)
        with pytest.raises(WorkflowError, match="不能为空"):
            await method(event, parent(), 0, "AI改写：", 123)
    asyncio.run(run())


@pytest.mark.parametrize("fixed", [True, False])
def test_aremake_final_submission_keeps_snapshot_and_prompt(tmp_path, fixed):
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
            _safety_policy=lambda: SimpleNamespace(fingerprint="same"),
            _safety_input=AsyncMock(), _safety_applies=lambda e: False,
            _event_source=lambda e: {}, _generation_slot=slot,
            _timeout_seconds=lambda: 1, _submit_workflow=AsyncMock(return_value="id"),
            _wait_for_history=AsyncMock(return_value={}),
            _download_images=AsyncMock(return_value=[tmp_path / "image.png"]),
            _character_dictionary_path=lambda: tmp_path / "dict.json",
            _safety_outputs=AsyncMock(side_effect=lambda e, paths: paths),
            _remake_modified=AsyncMock(), config={})
        event = SimpleNamespace(
            message_str="/aremake " + ("固定种子 " if fixed else "") + "blue bicycle",
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
        expected["11"]["inputs"]["text"] += ", blue bicycle"
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
