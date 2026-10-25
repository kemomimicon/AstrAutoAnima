"""Independent cross-feature local replay checks using synthetic files and HTTP mocks."""

import asyncio
import copy
import json

import pytest

try:
    from . import test_local_jobs as local_fixtures
except ImportError:
    import test_local_jobs as local_fixtures
from astr_auto_anima_hub.auth import SYSTEM_ADMIN
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest, RemakeOptions


@pytest.mark.parametrize(
    ("selection", "legacy"),
    [("style", False), ("character", False), ("both", True), ("none", True)],
)
def test_local_remake_frozen_graph_partial_presets_and_seed_zero(selection, legacy):
    async def run():
        fixture = local_fixtures.LocalJobsTests()
        fixture.setUp()
        settings, manager = fixture.settings, fixture.manager
        try:
            for name in (
                "art1.safetensors", "art2.safetensors",
                "actor1.safetensors", "actor2.safetensors",
            ):
                (settings.lora_root / name).write_bytes(b"synthetic LoRA fixture")
            presets = {
                "styles": {"art": {"prompt": "soft lighting", "loras": [
                    {"name": "art1.safetensors", "strength_model": 0.0, "strength_clip": 0.0},
                    {"name": "art2.safetensors", "strength_model": 0.8, "strength_clip": 0.4},
                ]}},
                "characters": {
                    "actor": {"prompt": "green eyes", "lora": {
                        "name": "actor1.safetensors", "strength_model": 0.7, "strength_clip": 0.5,
                    }},
                    "new-actor": {"prompt": "red eyes", "lora": {
                        "name": "actor2.safetensors", "strength_model": 1.0, "strength_clip": 1.0,
                    }},
                },
            }
            settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
            created = manager.create(RemoteJobCreateRequest(
                target_id="local", deliver_to_im=False, kind="hq",
                prompt="garden, walking", style="art", character="actor",
            ), SYSTEM_ADMIN)
            await asyncio.gather(*tuple(manager._tasks))
            original = manager.get(created.id)
            assert original.status == "succeeded", original.message
            original_meta = manager._read_meta(created.id)
            original_meta["seed"] = 0
            for node in original_meta["workflow"].values():
                if node.get("class_type") == "KSampler":
                    node["inputs"]["seed"] = 0
            if legacy:
                original_meta.pop("preset_snapshot")
            manager._write_meta(created.id, original_meta)
            graph_before = copy.deepcopy(original_meta["workflow"])

            if selection == "style":
                presets["styles"]["new-art"] = {"prompt": "sharp lighting", "loras": [{
                    "name": "art2.safetensors", "strength_model": 0.2, "strength_clip": 0.3,
                }]}
                # An untouched preset must survive even when its live entry is gone.
                presets["characters"].pop("actor")
                options = RemakeOptions(
                    style="new-art", fixed_seed=True, ratio="16:9", adjustment="smiling",
                )
                expected = ["art2.safetensors", "actor1.safetensors"]
            elif selection == "character":
                presets["styles"] = {}
                options = RemakeOptions(character="new-actor", fixed_seed=True)
                expected = ["art1.safetensors", "art2.safetensors", "actor2.safetensors"]
            elif selection == "both":
                options = RemakeOptions(character="new-actor", style="art", fixed_seed=True)
                expected = ["art1.safetensors", "art2.safetensors", "actor2.safetensors"]
            else:
                presets = {"styles": {}, "characters": {}}
                options = RemakeOptions(fixed_seed=True)
                expected = ["art1.safetensors", "art2.safetensors", "actor1.safetensors"]
            settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
            # The saved graph, not the now-invalid configured template, must win.
            settings.local_workflow_path.write_text("{}", encoding="utf-8")
            remade = manager.remake_image(
                created.id, original.images[0].id, SYSTEM_ADMIN, options,
            )
            await asyncio.gather(*tuple(manager._tasks))
            result = manager.get(remade.id)
            assert result.status == "succeeded", result.message
            current = manager._read_meta(remade.id)
            graph = current["workflow"]
            assert current["seed"] == 0
            assert [node["inputs"]["lora_name"] for node in graph.values()
                    if node["class_type"] == "LoraLoader"] == expected
            for node_id in ("19", "30"):
                assert graph[node_id]["inputs"]["seed"] == 0
                for key in ("steps", "cfg", "sampler_name", "scheduler"):
                    assert graph[node_id]["inputs"][key] == graph_before[node_id]["inputs"][key]
            for node in graph.values():
                for link in node.get("inputs", {}).values():
                    if isinstance(link, list) and len(link) == 2:
                        assert str(link[0]) in graph, link
            assert graph["12"]["inputs"]["text"] == graph_before["12"]["inputs"]["text"]
            if selection == "character":
                assert "soft lighting" in current["final_prompt"]
                assert "red eyes" in current["final_prompt"]
                assert "green eyes" not in current["final_prompt"]
                assert graph["990000"]["inputs"]["strength_model"] == 0.0
                assert graph["990000"]["inputs"]["strength_clip"] == 0.0
            if selection == "style":
                assert "green eyes" in current["final_prompt"]
                assert "sharp lighting" in current["final_prompt"]
                assert "soft lighting" not in current["final_prompt"]
                assert "smiling" in current["tags"]
                assert (graph["28"]["inputs"]["width"], graph["28"]["inputs"]["height"]) == (1536, 864)
            assert manager._read_meta(created.id)["workflow"] == graph_before
        finally:
            await manager.shutdown()
            fixture.tearDown()

    asyncio.run(run())
