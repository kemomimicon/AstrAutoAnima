"""V routing, immutable snapshots, and text-only collections (no GPU or network)."""
from __future__ import annotations

import asyncio
import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.auth import AuthPrincipal, SYSTEM_ADMIN
from astr_auto_anima_hub.local_generation import build_local_workflow
from astr_auto_anima_hub.local_jobs import LocalJobManager
from astr_auto_anima_hub.prompt_favorites import full_prompt, list_favorites
from astr_auto_anima_hub.remote_jobs import RemoteJobError
from astr_auto_anima_hub.schemas import RemakeOptions, RemoteJobCreateRequest
import test_local_jobs as local_fixture
from gufeng_fixture import create_gufeng_fixture


CARD = {
    "template_id": "V-cn-test-card", "prompt": "mountains, river, pine tree",
    "scene_zh": "山川松林", "selection_seed": 19,
    "provenance": {"catalog_id": "cn-test-card", "catalog_version": "0.4.0",
                   "title": "测试诗", "author": "测试作者", "origin": "cn"},
}
DEFAULT_PROMPT = "1girl, solo, " + CARD["prompt"]


class LocalVGroupTests(unittest.IsolatedAsyncioTestCase):
    setUp = local_fixture.LocalJobsTests.setUp
    tearDown = local_fixture.LocalJobsTests.tearDown

    def payload(self, **updates):
        return RemoteJobCreateRequest.model_validate({
            "target_id": "local", "deliver_to_im": False, "kind": "random",
            "custom_groups": ["V"], **updates})

    async def generate(self, **updates):
        with patch("astr_auto_anima_hub.local_jobs.gufeng_available", return_value=True), \
             patch("astr_auto_anima_hub.local_jobs.draw_gufeng", return_value=copy.deepcopy(CARD)) as draw:
            job = self.manager.create(self.payload(**updates), SYSTEM_ADMIN)
            await asyncio.gather(*tuple(self.manager._tasks))
            self.assertEqual(draw.call_count, 1)
        result = self.manager.get(job.id)
        self.assertEqual(result.status, "succeeded", result.message)
        return result

    async def test_empty_prompt_v_has_single_pass_no_llm_or_astrbot(self):
        result = await self.generate()
        meta = self.manager._read_meta(result.id)
        self.assertEqual(result.prompt_ids, [CARD["template_id"]])
        self.assertEqual(result.source_prompt, DEFAULT_PROMPT)
        self.assertEqual(result.prompt_provenance["safety_review"], "owner_confirmed_sfw")
        self.assertEqual(result.safety_code, "N")
        self.assertEqual(meta["template_snapshot"]["catalog_prompt"], CARD["prompt"])
        self.assertEqual(meta["template_snapshot"]["prompt"], DEFAULT_PROMPT)
        self.assertEqual(result.prompt_provenance["v_prefix_policy_version"], 1)
        self.assertEqual(result.prompt_provenance["random_subject_tag"], "1girl")
        self.assertEqual(meta["prompt_id"], "abc")  # Comfy ID never overwritten by template ID
        self.assertNotIn("30", meta["workflow"])
        self.assertEqual(meta["workflow"]["8"]["inputs"]["samples"], ["19", 0])
        self.assertEqual(result.final_prompt, DEFAULT_PROMPT)
        self.assertEqual({path for _, path, _ in self.calls}, {"/prompt", "/history/abc"})
        self.assertFalse(self.settings.prompt_pool_path.exists())
        self.assertFalse(self.settings.prompt_favorites_path.exists())

    async def test_real_sqlite_provider_to_mock_comfy_api(self):
        catalog = self.settings.plugin_data_dir.parent / "gufeng/cards.sqlite3"
        catalog.parent.mkdir()
        create_gufeng_fixture(catalog)
        settings = replace(self.settings, local_gufeng_catalog_path=catalog)
        manager = LocalJobManager(settings, transport=self.manager._transport)
        before = catalog.read_bytes()
        job = manager.create(self.payload(prompt="sunlight"))
        await asyncio.gather(*tuple(manager._tasks))
        result = manager.get(job.id)
        self.assertEqual(result.status, "succeeded", result.message)
        self.assertEqual(result.prompt_provenance["origin"], "cn")
        self.assertEqual(result.prompt_provenance["catalog_version"], "0.4.0")
        self.assertTrue(result.images[0].prompt_id.startswith("V:"))
        self.assertIn("sunlight", result.final_prompt)
        self.assertTrue(result.source_prompt.startswith("1girl, solo, "))
        snapshot = manager._read_meta(job.id)["template_snapshot"]
        self.assertEqual(snapshot["prompt"], "1girl, solo, " + snapshot["catalog_prompt"])
        self.assertEqual(catalog.read_bytes(), before)
        self.assertEqual({p.name for p in catalog.parent.iterdir()},
                         {"cards.sqlite3", "catalog_manifest.json"})

    async def test_subject_choices_only_prefix_new_snapshot_not_catalog(self):
        original_card = copy.deepcopy(CARD)
        for choice in ("", "1girl", "1boy", "1woman", "1man", "none"):
            with self.subTest(choice=choice):
                selected = choice or "1girl"
                prefix = "solo" if choice == "none" else f"{selected}, solo"
                result = await self.generate(random_subject_tag=choice, style="测试")
                snapshot = self.manager._read_meta(result.id)["template_snapshot"]
                self.assertEqual(snapshot["catalog_prompt"], CARD["prompt"])
                self.assertEqual(result.source_prompt, f"{prefix}, {CARD['prompt']}")
                self.assertEqual(result.images[0].source_prompt, result.source_prompt)
                self.assertTrue(result.final_prompt.startswith(prefix + ", soft light, "))
                self.assertEqual(result.prompt_provenance["random_subject_tag"], selected)
                self.assertEqual(snapshot["provenance"]["v_prefix_policy_version"], 1)
                if choice != "1girl" and choice:
                    self.assertNotIn("1girl", result.source_prompt)
        self.assertEqual(CARD, original_card)

    async def test_manual_additions_preserved_and_final_tags_deduplicated(self):
        for choice, addition, expected_tags in (
            ("", "1girl, solo, sunrise", {"1girl", "solo", "sunrise"}),
            ("", "1boy, sunrise", {"1girl", "1boy", "solo", "sunrise"}),
            ("none", "1girl, sunrise", {"1girl", "solo", "sunrise"}),
        ):
            with self.subTest(choice=choice, addition=addition):
                result = await self.generate(random_subject_tag=choice, prompt=addition)
                tags = result.final_prompt.split(", ")
                self.assertEqual(result.images[0].user_addition, addition)
                self.assertTrue(expected_tags.issubset(tags))
                for tag in expected_tags:
                    self.assertEqual(tags.count(tag), 1)
                self.assertEqual(self.manager._read_meta(result.id)["tags"],
                                 full_prompt(result.source_prompt, addition))

    async def test_legacy_queued_and_frozen_tasks_keep_no_prefix_policy(self):
        # Model a restart of a pre-policy task, both before and after drawing.
        for frozen in (False, True):
            with self.subTest(frozen=frozen):
                job = await self.generate(prompt="sunrise")
                meta = self.manager._read_meta(job.id)
                for key in ("workflow", "prompt_id", "seed", "tags", "final_prompt",
                            "preset_snapshot", "v_prefix_policy_version", "template_snapshot"):
                    meta.pop(key, None)
                if frozen:
                    meta["template_snapshot"] = copy.deepcopy(CARD)
                self.manager._write_meta(job.id, meta)
                self.manager._update(job.id, status="queued", images=[], prompt_provenance={})
                resumed = LocalJobManager(self.settings, transport=self.manager._transport)
                with patch("astr_auto_anima_hub.local_jobs.draw_gufeng",
                           return_value=copy.deepcopy(CARD)) as draw:
                    await resumed.resume()
                    await asyncio.gather(*tuple(resumed._tasks))
                    self.assertEqual(draw.call_count, 0 if frozen else 1)
                    result = resumed.get(job.id)
                    self.assertEqual(result.status, "succeeded", result.message)
                    self.assertEqual(result.images[0].source_prompt, CARD["prompt"])
                    self.assertNotIn("1girl", result.final_prompt)
                    self.assertNotIn("solo", result.final_prompt)
                    self.assertNotIn("v_prefix_policy_version", result.prompt_provenance)
                    remade = resumed.remake_image(result.id, result.images[0].id,
                                                  SYSTEM_ADMIN, RemakeOptions(adjustment="mist"))
                    await asyncio.gather(*tuple(resumed._tasks))
                result = resumed.get(remade.id)
                self.assertEqual(result.status, "succeeded", result.message)
                self.assertEqual(result.images[0].source_prompt, CARD["prompt"])
                self.assertNotIn("1girl", result.final_prompt)
                self.assertNotIn("solo", result.final_prompt)
                self.assertEqual(result.images[0].user_addition, "sunrise, mist")
                self.assertEqual(resumed._read_meta(remade.id)["template_snapshot"], CARD)
                # Stop the initial manager's stale queued copy entering the
                # next iteration (the restored manager has persisted success).
                self.manager._jobs[job.id] = resumed.get(job.id)

    async def test_addition_presets_lora_ratio_sampling_preserved(self):
        presets = json.loads(self.settings.preset_path.read_text("utf-8"))
        presets["characters"]["example"] = {"prompt": "silver hair", "lora": None}
        self.settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
        result = await self.generate(prompt="sunrise", character="example", style="测试",
                                     ratio="16:9", sampler="2m", scheduler="karras", steps=32, cfg=5.2)
        graph = self.manager._read_meta(result.id)["workflow"]
        self.assertEqual(graph["19"]["inputs"]["sampler_name"], "dpmpp_2m")
        self.assertEqual(graph["19"]["inputs"]["steps"], 32)
        self.assertEqual(graph["19"]["inputs"]["cfg"], 5.2)
        self.assertEqual(graph["28"]["inputs"]["width"], 1536)
        self.assertEqual(graph["990000"]["inputs"]["lora_name"], "style.safetensors")
        for tag in ("silver hair", "soft light", "sunrise", "mountains"):
            self.assertIn(tag, result.final_prompt)
        self.assertEqual(result.images[0].source_prompt, DEFAULT_PROMPT)
        self.assertEqual(result.images[0].user_addition, "sunrise")
        self.assertEqual(self.manager._read_meta(result.id)["tags"], full_prompt(DEFAULT_PROMPT, "sunrise"))

    async def test_unsupported_or_missing_v_never_submits(self):
        cases = [{"custom_groups": []}, {"custom_groups": ["other"]},
                 {"custom_groups": ["v", "other"]}, {"pool_filter": "N"},
                 {"five_draw": True},
                 {"task_suite_id": "a" * 32}, {"style": "随机模式"}]
        with patch("astr_auto_anima_hub.local_jobs.gufeng_available", return_value=True):
            for updates in cases:
                with self.subTest(updates=updates), self.assertRaises(RemoteJobError):
                    self.manager.create(self.payload(**updates))
            with self.assertRaises(RemoteJobError):
                self.manager.create(self.payload(), AuthPrincipal(role="user", subject="x"))
        with patch("astr_auto_anima_hub.local_jobs.gufeng_available", return_value=False):
            with self.assertRaisesRegex(RemoteJobError, "资源组件"):
                self.manager.create(self.payload())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.manager._jobs, {})

    async def test_catalog_failure_is_clear_and_never_submits(self):
        with patch("astr_auto_anima_hub.local_jobs.gufeng_available", return_value=True), \
             patch("astr_auto_anima_hub.local_jobs.draw_gufeng", side_effect=ValueError("中华候选为空")):
            job = self.manager.create(self.payload())
            await asyncio.gather(*tuple(self.manager._tasks))
        self.assertEqual(self.manager.get(job.id).status, "failed")
        self.assertIn("中华候选为空", self.manager.get(job.id).message)
        self.assertEqual(self.calls, [])

    async def test_remake_keeps_template_and_seed_even_if_catalog_uninstalled(self):
        original = await self.generate(prompt="sunrise", style="测试")
        original_meta = self.manager._read_meta(original.id)
        with patch("astr_auto_anima_hub.local_jobs.draw_gufeng", side_effect=AssertionError("must not redraw")):
            remade = self.manager.remake_image(original.id, original.images[0].id, SYSTEM_ADMIN,
                                               RemakeOptions(fixed_seed=True, ratio="1:1", adjustment="mist"))
            await asyncio.gather(*tuple(self.manager._tasks))
            result = self.manager.get(remade.id)
            self.assertEqual(result.status, "succeeded", result.message)
            self.assertEqual(result.prompt_ids, original.prompt_ids)
            self.assertEqual(result.prompt_provenance, original.prompt_provenance)
            meta = self.manager._read_meta(remade.id)
            self.assertEqual(meta["seed"], original_meta["seed"])
            self.assertEqual(meta["template_snapshot"], original_meta["template_snapshot"])
            self.assertEqual(meta["user_addition"], "sunrise, mist")
            self.assertEqual(meta["tags"], full_prompt(DEFAULT_PROMPT, "sunrise, mist"))
            self.assertEqual(result.images[0].user_addition, "sunrise, mist")
            self.assertEqual(result.final_prompt.count("mist"), 1)
            self.assertIn("soft light", result.final_prompt)
            self.assertEqual(meta["workflow"]["28"]["inputs"]["width"], 1024)
            # A second remake retains accumulated additions without duplication.
            again = self.manager.remake_image(result.id, result.images[0].id, SYSTEM_ADMIN,
                                               RemakeOptions(adjustment="clouds"))
            await asyncio.gather(*tuple(self.manager._tasks))
            self.assertEqual(self.manager.get(again.id).images[0].user_addition, "sunrise, mist, clouds")
            second = self.manager.get(again.id)
            self.assertEqual(second.images[0].source_prompt, DEFAULT_PROMPT)
            self.assertEqual(second.final_prompt.count("1girl"), 1)
            self.assertEqual(second.final_prompt.count("solo"), 1)
            self.assertEqual(second.prompt_provenance, original.prompt_provenance)

    async def test_restart_keeps_provenance_without_resubmit_or_redraw(self):
        job = await self.generate()
        self.manager._update(job.id, status="running")
        self.calls.clear()
        resumed = LocalJobManager(self.settings, transport=self.manager._transport)
        with patch("astr_auto_anima_hub.local_jobs.draw_gufeng", side_effect=AssertionError("must not redraw")):
            await resumed.resume()
            await asyncio.gather(*tuple(resumed._tasks))
        self.assertEqual(resumed.get(job.id).status, "succeeded")
        self.assertEqual(resumed.get(job.id).prompt_provenance, job.prompt_provenance)
        self.assertEqual(resumed.get(job.id).images[0].prompt_id, CARD["template_id"])
        self.assertNotIn("/prompt", [path for _, path, _ in self.calls])

    async def test_resume_before_submission_uses_frozen_card_without_catalog(self):
        job = await self.generate(prompt="sunrise")
        meta = self.manager._read_meta(job.id)
        for key in ("workflow", "prompt_id", "seed", "tags", "final_prompt", "preset_snapshot"):
            meta.pop(key, None)
        self.manager._write_meta(job.id, meta)
        self.manager._update(job.id, status="queued", images=[])
        self.calls.clear()
        resumed = LocalJobManager(replace(self.settings, local_gufeng_catalog_path=None),
                                  transport=self.manager._transport)
        with patch("astr_auto_anima_hub.local_jobs.draw_gufeng", side_effect=AssertionError("must not redraw")):
            await resumed.resume()
            await asyncio.gather(*tuple(resumed._tasks))
        result = resumed.get(job.id)
        self.assertEqual(result.status, "succeeded", result.message)
        self.assertEqual(result.images[0].source_prompt, DEFAULT_PROMPT)
        self.assertEqual(result.images[0].user_addition, "sunrise")
        self.assertEqual(sum(path == "/prompt" for _, path, _ in self.calls), 1)

    async def test_v_style_only_remake_retains_deleted_character_snapshot(self):
        presets = json.loads(self.settings.preset_path.read_text("utf-8"))
        presets["characters"]["old"] = {"prompt": "silver hair", "lora": {
            "name": "style.safetensors", "strength_model": 0.3, "strength_clip": 0.2}}
        self.settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
        original = await self.generate(character="old", style="测试", prompt="sunrise")
        frozen = self.manager._read_meta(original.id)["preset_snapshot"]["character"]
        presets["characters"] = {}
        presets["styles"]["new"] = {"prompt": "watercolor", "loras": []}
        self.settings.preset_path.write_text(json.dumps(presets), encoding="utf-8")
        with patch("astr_auto_anima_hub.local_jobs.draw_gufeng", side_effect=AssertionError("must not redraw")):
            remade = self.manager.remake_image(original.id, original.images[0].id, SYSTEM_ADMIN,
                                               RemakeOptions(style="new", adjustment="mist"))
            await asyncio.gather(*tuple(self.manager._tasks))
            result = self.manager.get(remade.id)
            self.assertEqual(result.status, "succeeded", result.message)
            self.assertEqual(self.manager._read_meta(result.id)["preset_snapshot"]["character"], frozen)
            self.assertIn("silver hair", result.final_prompt)
            self.assertIn("watercolor", result.final_prompt)
            self.assertNotIn("soft light", result.final_prompt)
            again = self.manager.remake_image(result.id, result.images[0].id, SYSTEM_ADMIN)
            await asyncio.gather(*tuple(self.manager._tasks))
        second = self.manager.get(again.id)
        self.assertEqual(second.status, "succeeded", second.message)
        self.assertEqual(second.final_prompt, result.final_prompt)
        self.assertEqual(second.images[0].user_addition, "sunrise, mist")

    async def test_api_favorite_dedup_is_text_only_and_main_pool_untouched(self):
        principal = AuthPrincipal(role="admin", subject="administrator")
        app = create_app(self.settings)
        app.state.remote_jobs = self.manager
        headers = {"Authorization": "Bearer " + self.settings.admin_token}
        with patch("astr_auto_anima_hub.local_jobs.gufeng_available", return_value=True), \
             patch("astr_auto_anima_hub.local_jobs.draw_gufeng", return_value=copy.deepcopy(CARD)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/lite/jobs", headers=headers,
                                             json=self.payload(prompt="sunrise").model_dump())
                self.assertEqual(response.status_code, 202, response.text)
                await asyncio.gather(*tuple(self.manager._tasks))
                job = self.manager.get(response.json()["id"], principal)
                image_id = job.images[0].id
                before = sorted(str(p) for p in self.settings.plugin_data_dir.rglob("*.png"))
                path = f"/api/v1/lite/jobs/{job.id}/images/{image_id}/favorite"
                first = await client.post(path, headers=headers)
                second = await client.post(path, headers=headers)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.json()["action"], "liked")
                self.assertEqual(second.json()["action"], "already_liked")
                self.assertEqual(before, sorted(str(p) for p in self.settings.plugin_data_dir.rglob("*.png")))
        page = list_favorites(self.settings.prompt_favorites_path, principal)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].prompt, job.final_prompt)
        self.assertIn('sunrise', page.items[0].prompt)
        self.assertEqual(page.items[0].safety_code, "N")
        self.assertFalse(self.settings.prompt_pool_path.exists())

    async def test_capability_is_authenticated_and_requires_installed_catalog(self):
        for mode, installed, expected in (("local", True, 1), ("local", False, 0), ("remote", True, 1), ("remote", False, 0)):
            with self.subTest(mode=mode, installed=installed):
                app = create_app(replace(self.settings, execution_mode=mode))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    denied = await client.get("/api/v1/lite/local-capabilities")
                    self.assertEqual(denied.status_code, 401)
                    with patch("astr_auto_anima_hub.local_gufeng.gufeng_available", return_value=installed):
                        response = await client.get("/api/v1/lite/local-capabilities", headers={
                            "Authorization": "Bearer " + self.settings.admin_token})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(len(response.json()["random_groups"]), expected)
                    self.assertEqual(response.json()["execution_mode"], mode)

    async def test_sampler_aliases_generate_real_comfy_names(self):
        for alias, actual in (("2m", "dpmpp_2m"), ("2m_sde", "dpmpp_2m_sde"),
                              ("2m_sde_gpu", "dpmpp_2m_sde_gpu")):
            graph, _, _ = build_local_workflow(self.settings, self.payload(sampler=alias), CARD["prompt"])
            self.assertEqual(graph["19"]["inputs"]["sampler_name"], actual)


if __name__ == "__main__":
    unittest.main()
