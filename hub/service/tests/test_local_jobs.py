from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from astr_auto_anima_hub.auth import SYSTEM_ADMIN
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.local_generation import build_local_workflow, LocalGenerationError
from astr_auto_anima_hub.local_jobs import LocalJobManager
from astr_auto_anima_hub.remote_jobs import RemoteJobError
from astr_auto_anima_hub.schemas import ProbeStatus, RemakeOptions, RemoteJobCreateRequest
from astr_auto_anima_hub.probes import collect_workstation_status


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII="
)


class LocalJobsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        comfy = root / "ComfyUI"
        (comfy / "output" / "AAA-Local").mkdir(parents=True)
        (comfy / "models" / "loras").mkdir(parents=True)
        (comfy / "models" / "loras" / "style.safetensors").write_bytes(b"lora")
        (comfy / "output" / "AAA-Local" / "test.png").write_bytes(PNG)
        workflow = root / "workflow.json"
        workflow.write_text(json.dumps({
            "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "old", "clip": ["46", 1]}},
            "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["46", 1]}},
            "19": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["46", 0],
                     "steps": 25, "cfg": 4, "sampler_name": "er_sde", "scheduler": "normal",
                     "positive": ["11", 0], "negative": ["12", 0], "latent_image": ["28", 0]}},
            "28": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1536}},
            "29": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["19", 0]}},
            "30": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["46", 0],
                     "steps": 18, "cfg": 4, "sampler_name": "er_sde", "scheduler": "normal",
                     "positive": ["11", 0], "negative": ["12", 0], "latent_image": ["29", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
            "44": {"class_type": "UNETLoader", "inputs": {"unet_name": "base"}},
            "45": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip"}},
            "46": {"class_type": "LoraLoader", "inputs": {"lora_name": "old.safetensors",
                     "strength_model": 1, "strength_clip": 1,
                     "model": ["44", 0], "clip": ["45", 0]}},
        }), encoding="utf-8")
        presets = root / "presets.json"
        presets.write_text(json.dumps({"styles": {"测试": {"prompt": "soft light",
                             "loras": [{"name": "style.safetensors", "strength_model": 0.7,
                                        "strength_clip": 0.6}]}}, "characters": {}}), encoding="utf-8")
        self.settings = Settings(
            execution_mode="local", admin_token="a" * 32,
            plugin_data_dir=root / "data", comfyui_root=comfy,
            preset_override=presets, local_workflow_path=workflow,
            local_llm_base_url="http://llm.test/v1", local_llm_model="test-model",
        )
        self.calls = []

        def respond(request):
            self.calls.append((request.method, request.url.path, request.content))
            if request.url.path == "/v1/chat/completions":
                return httpx.Response(200, json={"choices": [{"message": {
                    "content": "tags: 1girl, solo, rainy street"}}]})
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "abc"})
            if request.url.path == "/history/abc":
                return httpx.Response(200, json={"abc": {"outputs": {"9": {
                    "images": [{"filename": "test.png", "subfolder": "AAA-Local", "type": "output"}]}}}})
            raise AssertionError(request.url)

        self.manager = LocalJobManager(self.settings, transport=httpx.MockTransport(respond))

    def tearDown(self):
        self.temp.cleanup()

    async def test_chinese_runs_without_astrbot_and_keeps_prompts(self):
        payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                         kind="chinese", prompt="雨夜的女孩", style="测试")
        created = self.manager.create(payload, SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        result = self.manager.get(created.id, SYSTEM_ADMIN)
        self.assertEqual(result.status, "succeeded", result.message)
        self.assertEqual(result.source_prompt, "雨夜的女孩")
        self.assertEqual(result.converted_prompt, "1girl, solo, rainy street")
        self.assertEqual(result.final_prompt, "1girl, solo, soft light, rainy street")
        self.assertEqual(len(result.images), 1)
        self.assertIn("/v1/chat/completions", [path for _, path, _ in self.calls])
        self.assertNotIn("/api/v1/chat", [path for _, path, _ in self.calls])
        submitted = next(json.loads(content) for method, path, content in self.calls if path == "/prompt")
        graph = submitted["prompt"]
        self.assertNotIn("46", graph)
        self.assertEqual(graph["990000"]["inputs"]["lora_name"], "style.safetensors")
        self.assertEqual(graph["990000"]["inputs"]["model"], ["44", 0])
        self.assertEqual(graph["19"]["inputs"]["model"], ["990000", 0])

    async def test_direct_without_preset_bypasses_template_lora(self):
        payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                         kind="direct", prompt="1girl")
        graph, _, _ = build_local_workflow(self.settings, payload, "1girl")
        self.assertNotIn("46", graph)
        self.assertEqual(graph["19"]["inputs"]["model"], ["44", 0])
        self.assertEqual(graph["11"]["inputs"]["clip"], ["45", 0])
        self.assertNotIn("29", graph)
        self.assertNotIn("30", graph)
        self.assertEqual(graph["8"]["inputs"]["samples"], ["19", 0])

    async def test_base_model_outfit_and_remake_without_character_lora(self):
        data = json.loads(self.settings.preset_path.read_text(encoding="utf-8"))
        data["characters"]["Base"] = {"prompt": "base_character, uniform", "lora": None,
            "variants": [{"id": "dress", "name": "裙装", "category": "clothing",
                          "prompt": "base_character, dress"}]}
        self.settings.preset_path.write_text(json.dumps(data), encoding="utf-8")
        for kind in ("direct", "hq", "chinese"):
            payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                kind=kind, prompt="smiling", character="Base", character_variant="dress")
            graph, _, prompt = build_local_workflow(self.settings, payload, "smiling")
            self.assertIn("base_character", prompt)
            self.assertIn("dress", prompt)
            self.assertNotIn("uniform", prompt)
            self.assertFalse(any(n["class_type"] == "LoraLoader" for n in graph.values()))
            self.assertEqual(graph["19"]["inputs"]["model"], ["44", 0])
            self.assertEqual(graph["11"]["inputs"]["clip"], ["45", 0])
        created = self.manager.create(payload, SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        original = self.manager.get(created.id, SYSTEM_ADMIN)
        self.assertEqual(original.status, "succeeded", original.message)
        remade = self.manager.remake_image(created.id, original.images[0].id, SYSTEM_ADMIN,
                                          options=RemakeOptions(fixed_seed=True))
        await asyncio.gather(*tuple(self.manager._tasks))
        result = self.manager.get(remade.id, SYSTEM_ADMIN)
        self.assertEqual(result.status, "succeeded", result.message)
        self.assertEqual(result.final_prompt, original.final_prompt)
        _, _, default = build_local_workflow(self.settings,
            payload.model_copy(update={"character_variant": "default"}), "smiling")
        self.assertIn("uniform", default)
        self.assertNotIn("dress", default)
        graph, _, _ = build_local_workflow(self.settings,
            payload.model_copy(update={"style": "测试"}), "smiling")
        loras = [n for n in graph.values() if n["class_type"] == "LoraLoader"]
        self.assertEqual([n["inputs"]["lora_name"] for n in loras], ["style.safetensors"])
        with self.assertRaises(LocalGenerationError):
            build_local_workflow(self.settings,
                payload.model_copy(update={"character_variant": "missing"}), "smiling")

    async def test_hq_keeps_second_pass_and_updates_shared_parameters(self):
        payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                         kind="hq", prompt="1girl", cfg=5.5,
                                         sampler="euler")
        graph, seed, _ = build_local_workflow(self.settings, payload, "1girl")
        self.assertIn("30", graph)
        self.assertEqual(graph["8"]["inputs"]["samples"], ["30", 0])
        for node_id in ("19", "30"):
            self.assertEqual(graph[node_id]["inputs"]["seed"], seed)
            self.assertEqual(graph[node_id]["inputs"]["cfg"], 5.5)
            self.assertEqual(graph[node_id]["inputs"]["sampler_name"], "euler")

    async def test_bundled_workflow_direct_and_hq_have_no_dangling_nodes(self):
        bundle = (Path(__file__).resolve().parents[3] / "comfyui" / "workflows" /
                  "Anima_HQ_Txt2Img_Beta_api.json")
        if not bundle.is_file():
            self.skipTest("bundled workflow is not in this checkout")
        settings = replace(self.settings, local_workflow_path=bundle)
        for kind in ("direct", "chinese", "hq"):
            payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                             kind=kind, prompt="1girl")
            graph, _, _ = build_local_workflow(settings, payload, "1girl")
            self.assertEqual("30" in graph, kind == "hq")
            for node in graph.values():
                for link in node.get("inputs", {}).values():
                    if isinstance(link, list) and len(link) == 2:
                        self.assertIn(str(link[0]), graph)

    async def test_local_remake_uses_saved_graph_and_seed_policy(self):
        created = self.manager.create(RemoteJobCreateRequest(
            target_id="local", deliver_to_im=False, kind="direct", prompt="1girl"), SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        original = self.manager.get(created.id, SYSTEM_ADMIN)
        original_meta = self.manager._read_meta(created.id)
        remade = self.manager.remake_image(created.id, original.images[0].id, SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        self.assertEqual(self.manager.get(remade.id, SYSTEM_ADMIN).status, "succeeded")
        self.assertNotEqual(self.manager._read_meta(remade.id)["seed"], original_meta["seed"])
        fixed = self.manager.remake_image(created.id, original.images[0].id, SYSTEM_ADMIN,
                                          options=RemakeOptions(
                                              fixed_seed=True, ratio="1:1", adjustment="rainy street"))
        await asyncio.gather(*tuple(self.manager._tasks))
        fixed_meta = self.manager._read_meta(fixed.id)
        self.assertEqual(fixed_meta["seed"], original_meta["seed"])
        self.assertEqual(fixed_meta["workflow"]["28"]["inputs"]["width"], 1024)
        self.assertIn("rainy street", fixed_meta["workflow"]["11"]["inputs"]["text"])

    async def test_resume_checks_existing_comfy_task_without_resubmission(self):
        created = self.manager.create(RemoteJobCreateRequest(
            target_id="local", deliver_to_im=False, kind="direct", prompt="1girl"), SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        self.manager._update(created.id, status="running")
        self.calls.clear()
        resumed = LocalJobManager(self.settings, transport=self.manager._transport)
        await resumed.resume()
        await asyncio.gather(*tuple(resumed._tasks))
        self.assertEqual(resumed.get(created.id, SYSTEM_ADMIN).status, "succeeded")
        self.assertNotIn("/prompt", [path for _, path, _ in self.calls])

    async def test_shutdown_keeps_submitted_job_recoverable(self):
        def waiting(request):
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "abc"})
            if request.url.path == "/history/abc":
                return httpx.Response(200, json={})
            raise AssertionError(request.url)
        pending = LocalJobManager(self.settings, transport=httpx.MockTransport(waiting))
        created = pending.create(RemoteJobCreateRequest(
            target_id="local", deliver_to_im=False, kind="direct", prompt="1girl"), SYSTEM_ADMIN)
        for _ in range(100):
            if pending._read_meta(created.id).get("prompt_id"):
                break
            await asyncio.sleep(0.01)
        self.assertEqual(pending._read_meta(created.id).get("prompt_id"), "abc")
        await pending.shutdown()
        self.assertEqual(pending.get(created.id, SYSTEM_ADMIN).status, "running")
        recovered = LocalJobManager(self.settings, transport=self.manager._transport)
        await recovered.resume()
        await asyncio.gather(*tuple(recovered._tasks))
        self.assertEqual(recovered.get(created.id, SYSTEM_ADMIN).status, "succeeded")

    async def test_local_api_submit_history_and_remake_route(self):
        app = create_app(self.settings)
        app.state.remote_jobs = self.manager
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer " + self.settings.admin_token}
            submitted = await client.post("/api/v1/lite/jobs", headers=headers,
                json={"target_id": "local", "deliver_to_im": False,
                      "kind": "direct", "prompt": "1girl"})
            self.assertEqual(submitted.status_code, 202, submitted.text)
            await asyncio.gather(*tuple(self.manager._tasks))
            job_id = submitted.json()["id"]
            listed = await client.get("/api/v1/lite/jobs", headers=headers)
            self.assertEqual(listed.status_code, 200)
            image_id = listed.json()["items"][0]["images"][0]["id"]
            remake = await client.post(
                f"/api/v1/lite/jobs/{job_id}/images/{image_id}/remake",
                headers=headers, json={"fixed_seed": True})
            self.assertEqual(remake.status_code, 202, remake.text)
            await asyncio.gather(*tuple(self.manager._tasks))
            self.assertEqual(self.manager.get(remake.json()["id"], SYSTEM_ADMIN).status,
                             "succeeded")

    async def test_dictionary_chinese_name_and_off_mode(self):
        entry = SimpleNamespace(tag="example_character", chinese_names=["示例角色"],
                                aliases=[], disabled=False, weak_prompt="example_character",
                                strong_prompt="example_character, blue eyes")
        payload = RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                         kind="direct", prompt="smiling", character="示例角色",
                                         character_tag_mode="strong")
        with patch("astr_auto_anima_hub.local_generation.search_character_dictionary",
                   return_value=SimpleNamespace(items=[entry])):
            _, _, prompt = build_local_workflow(self.settings, payload, "smiling")
        self.assertIn("blue eyes", prompt)
        raw = payload.model_copy(update={"character_tag_mode": "off"})
        _, _, raw_prompt = build_local_workflow(self.settings, raw, "smiling")
        self.assertIn("示例角色", raw_prompt)

    async def test_local_never_falls_back_to_astrbot(self):
        with self.assertRaisesRegex(RemoteJobError, "尚未接入"):
            self.manager.create(RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                                       kind="reverse", prompt="test"), SYSTEM_ADMIN)
        with self.assertRaisesRegex(RemoteJobError, "不能投递"):
            self.manager.create(RemoteJobCreateRequest(target_id="local", kind="direct",
                                                       prompt="test"), SYSTEM_ADMIN)
        with self.assertRaisesRegex(RemoteJobError, "高级参数"):
            self.manager.create(RemoteJobCreateRequest(target_id="local", deliver_to_im=False,
                                                       kind="direct", prompt="test",
                                                       custom_groups=["example"]), SYSTEM_ADMIN)

    async def test_remake_preset_edit_keeps_frozen_graph_and_untouched_preset(self):
        presets = json.loads(self.settings.preset_path.read_text(encoding="utf-8"))
        presets["characters"]["old-character"] = {"prompt": "green eyes", "lora": None}
        self.settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
        created = self.manager.create(RemoteJobCreateRequest(
            target_id="local", deliver_to_im=False, kind="hq", prompt="1girl, garden",
            character="old-character", style="测试"), SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        job = self.manager.get(created.id, SYSTEM_ADMIN)
        original = self.manager._read_meta(created.id)
        template = json.loads(self.settings.local_workflow_path.read_text(encoding="utf-8"))
        for node_id in ("19", "30"):
            template[node_id]["inputs"].update(steps=40, cfg=8, sampler_name="euler",
                                               scheduler="karras", denoise=0.3)
        template["44"]["inputs"]["unet_name"] = "different-model"
        template["12"]["inputs"]["text"] = "different-negative"
        self.settings.local_workflow_path.write_text(json.dumps(template), encoding="utf-8")
        presets["characters"] = {}  # untouched character must not be read again
        presets["styles"]["测试"]["prompt"] = "new selected lighting"
        self.settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
        remade = self.manager.remake_image(created.id, job.images[0].id, SYSTEM_ADMIN,
                                          RemakeOptions(style="测试", fixed_seed=True, ratio="1:1"))
        await asyncio.gather(*tuple(self.manager._tasks))
        self.assertEqual(self.manager.get(remade.id).status, "succeeded", self.manager.get(remade.id).message)
        current = self.manager._read_meta(remade.id)
        for node_id in ("19", "30"):
            self.assertEqual(current["workflow"][node_id], original["workflow"][node_id])
        self.assertEqual(current["workflow"]["44"], original["workflow"]["44"])
        self.assertEqual(current["workflow"]["12"], original["workflow"]["12"])
        self.assertEqual(current["workflow"]["28"]["inputs"]["height"], 1024)
        self.assertIn("green eyes", current["final_prompt"])
        self.assertIn("new selected lighting", current["final_prompt"])
        self.assertNotIn("soft light", current["final_prompt"])
        self.assertEqual(current["preset_snapshot"]["character"], original["preset_snapshot"]["character"])

    async def test_legacy_remake_refuses_guessing_untouched_preset(self):
        created = self.manager.create(RemoteJobCreateRequest(
            target_id="local", deliver_to_im=False, kind="direct", prompt="1girl", style="测试"), SYSTEM_ADMIN)
        await asyncio.gather(*tuple(self.manager._tasks))
        job = self.manager.get(created.id)
        meta = self.manager._read_meta(created.id)
        del meta["preset_snapshot"]
        self.manager._write_meta(created.id, meta)
        self.calls.clear()
        remade = self.manager.remake_image(created.id, job.images[0].id, SYSTEM_ADMIN,
                                          RemakeOptions(character="raw tag"))
        await asyncio.gather(*tuple(self.manager._tasks))
        self.assertEqual(self.manager.get(remade.id).status, "failed")
        self.assertIn("旧任务缺少", self.manager.get(remade.id).message)
        self.assertNotIn("/prompt", [path for _, path, _ in self.calls])

    async def test_health_identifies_local_mode(self):
        with TestClient(create_app(self.settings)) as client:
            response = client.get("/api/v1/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["execution_mode"], "local")

    async def test_local_mode_rejects_public_comfyui_url(self):
        unsafe = replace(self.settings, comfyui_url="http://0.0.0.0:8188")
        with self.assertRaisesRegex(ValueError, "loopback ComfyUI"):
            unsafe.validate_for_startup()

    async def test_local_workstation_status_never_probes_astrbot(self):
        names = []

        def http_probe(name, *_args, **_kwargs):
            names.append(name)
            return ProbeStatus(name=name, status="online")

        with patch("astr_auto_anima_hub.probes._http_probe", side_effect=http_probe), \
             patch("astr_auto_anima_hub.probes._gpu_probe",
                   return_value=ProbeStatus(name="gpu", status="unknown")):
            status = await collect_workstation_status(self.settings)
        self.assertEqual(names, ["comfyui"])
        self.assertEqual(status.status, "ready")
        self.assertNotIn("astrbot", [probe.name for probe in status.probes])
