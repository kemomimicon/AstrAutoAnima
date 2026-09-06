import json
import tempfile
import unittest
from pathlib import Path

from job_runtime import JobStore, sha256_file
from workflow_registry import (
    load_workflow_registry,
    validate_workflow_nodes,
)
from workflow_runtime import (
    WorkflowError,
    configure_hq_workflow,
    configure_refine_workflow,
    configure_seedvr2_workflow,
)


RELEASE_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = RELEASE_ROOT / "comfyui" / "workflows"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class WorkflowRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_workflow_registry(
            PLUGIN_ROOT / "data" / "workflow_registry.json"
        )

    def test_registry_exposes_quick_hq_refine_and_reverse(self):
        self.assertEqual(
            self.registry.ids(),
            (
                "hq_txt2img_anima_v1",
                "quick_txt2img_v1",
                "refine_existing_v1",
                "reverse_anime_v1",
                "seedvr2_refine_v1",
            ),
        )

    def test_hq_and_refine_profiles_have_expected_defaults(self):
        hq = self.registry.resolve("hq_txt2img_anima_v1")
        name, stable = hq.profile("")
        self.assertEqual(name, "stable")
        self.assertEqual(stable["sampling"]["sampler_name"], "er_sde")
        self.assertEqual(stable["enhance"]["scale"], 1.25)
        self.assertEqual(hq.profile("beauty")[1]["enhance"]["denoise"], 0.30)

        refine = self.registry.resolve("refine_existing_v1")
        self.assertEqual(refine.profile("")[0], "light")
        self.assertEqual(refine.profile("medium")[1]["enhance"]["scale"], 1.5)

        seedvr2 = self.registry.resolve("seedvr2_refine_v1")
        self.assertEqual(seedvr2.profile("")[0], "seedvr2")
        self.assertEqual(
            seedvr2.profile("seedvr2")[1]["enhance"]["target_resolution"],
            4096,
        )

    def test_unknown_workflow_and_profile_fail_clearly(self):
        with self.assertRaisesRegex(WorkflowError, "WORKFLOW_NOT_FOUND"):
            self.registry.resolve("missing")
        with self.assertRaisesRegex(WorkflowError, "PROFILE_NOT_FOUND"):
            self.registry.resolve("hq_txt2img_anima_v1").profile("ultra")

    def test_delivered_workflows_satisfy_registry_contracts(self):
        pairs = (
            (
                "hq_txt2img_anima_v1",
                WORKFLOW_ROOT / "Anima_HQ_Txt2Img_Beta_api.json",
            ),
            (
                "refine_existing_v1",
                WORKFLOW_ROOT / "Anima_Refine_Existing_Beta_api.json",
            ),
            (
                "seedvr2_refine_v1",
                WORKFLOW_ROOT / "Anima_SeedVR2_Refine_Beta_api.json",
            ),
        )
        for workflow_id, path in pairs:
            with self.subTest(workflow=workflow_id):
                validate_workflow_nodes(
                    load_json(path), self.registry.resolve(workflow_id)
                )


class HqRefineConfigurationTests(unittest.TestCase):
    def test_hq_profile_configures_both_stages_and_syncs_lora_chain(self):
        workflow = load_json(
            WORKFLOW_ROOT / "Anima_HQ_Txt2Img_Beta_api.json"
        )
        workflow["19"]["inputs"]["model"] = ["900001", 0]
        workflow["19"]["inputs"]["positive"] = ["11", 0]
        workflow["19"]["inputs"]["negative"] = ["12", 0]
        profile = {
            "sampling": {
                "sampler_name": "er_sde",
                "scheduler": "normal",
                "steps": 34,
                "cfg": 4.5,
                "denoise": 1.0,
            },
            "enhance": {
                "scale": 1.25,
                "steps": 18,
                "cfg": 4.5,
                "sampler_name": "er_sde",
                "scheduler": "normal",
                "denoise": 0.28,
            },
        }
        result = configure_hq_workflow(
            workflow,
            sampler_node_id="19",
            upscale_node_id="29",
            refiner_sampler_node_id="30",
            profile=profile,
            seed=123,
            scale_override=1.4,
            denoise_override=0.32,
        )
        second = workflow["30"]["inputs"]
        self.assertEqual(workflow["29"]["inputs"]["scale_by"], 1.4)
        self.assertEqual(second["model"], ["900001", 0])
        self.assertEqual(second["seed"], 123)
        self.assertEqual(second["steps"], 18)
        self.assertEqual(second["denoise"], 0.32)
        self.assertEqual(result["scale"], 1.4)

    def test_refine_profile_injects_image_and_overrides(self):
        workflow = load_json(
            WORKFLOW_ROOT / "Anima_Refine_Existing_Beta_api.json"
        )
        result = configure_refine_workflow(
            workflow,
            image_name="incoming/source.png",
            image_node_id="1",
            upscale_node_id="2",
            sampler_node_id="19",
            profile={
                "sampling": {
                    "sampler_name": "er_sde",
                    "scheduler": "normal",
                    "steps": 18,
                    "cfg": 4.5,
                    "denoise": 0.25,
                },
                "enhance": {"scale": 1.25, "denoise": 0.25},
            },
            seed=456,
            scale_override=1.5,
            denoise_override=0.35,
        )
        self.assertEqual(workflow["1"]["inputs"]["image"], "incoming/source.png")
        self.assertEqual(workflow["2"]["inputs"]["scale_by"], 1.5)
        self.assertEqual(workflow["19"]["inputs"]["seed"], 456)
        self.assertEqual(workflow["19"]["inputs"]["denoise"], 0.35)
        self.assertEqual(result["scale"], 1.5)

    def test_invalid_enhancement_values_are_rejected(self):
        workflow = load_json(
            WORKFLOW_ROOT / "Anima_Refine_Existing_Beta_api.json"
        )
        with self.assertRaisesRegex(WorkflowError, "scale"):
            configure_refine_workflow(
                workflow,
                image_name="source.png",
                image_node_id="1",
                upscale_node_id="2",
                sampler_node_id="19",
                profile={"sampling": {}, "enhance": {}},
                seed=1,
                scale_override=3.0,
            )

    def test_seedvr2_injects_image_seed_and_tiling_profile(self):
        workflow = load_json(
            WORKFLOW_ROOT / "Anima_SeedVR2_Refine_Beta_api.json"
        )
        result = configure_seedvr2_workflow(
            workflow,
            image_name="incoming/source.png",
            image_node_id="1",
            upscaler_node_id="4",
            profile={
                "enhance": {
                    "target_resolution": 4096,
                    "tile_width": 1024,
                    "tile_height": 1024,
                    "tile_padding": 64,
                    "tile_upscale_resolution": 1536,
                    "mask_blur": 3,
                    "anti_aliasing_strength": 0.1,
                }
            },
            seed=789,
        )
        inputs = workflow["4"]["inputs"]
        self.assertEqual(workflow["1"]["inputs"]["image"], "incoming/source.png")
        self.assertEqual(inputs["seed"], 789)
        self.assertEqual(inputs["new_resolution"], 4096)
        self.assertEqual(inputs["tile_width"], 1024)
        self.assertEqual(inputs["tile_padding"], 64)
        self.assertEqual(result["target_resolution"], 4096)


class JobStoreTests(unittest.TestCase):
    def test_job_asset_and_parent_lookup_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "result.png"
            image.write_bytes(b"fake-image")
            store = JobStore(root / "runtime")
            job = store.create_job(
                workflow_type="hq_txt2img_anima_v1",
                workflow_version="1.0.0-beta.1",
                profile="stable",
                source={"qq_user_id": "10001", "session_type": "private"},
                input_data={"prompt": "1girl, rainy street"},
            )
            asset = store.register_asset(
                image,
                asset_type="output",
                job_id=job["job_id"],
                source="plugin_download",
            )
            job["status"] = "succeeded"
            job["result"]["assets"].append(asset["asset_id"])
            store.save_job(job)

            self.assertEqual(asset["sha256"], sha256_file(image))
            found_asset, parent = store.parent_for_image(image)
            self.assertEqual(found_asset["asset_id"], asset["asset_id"])
            self.assertEqual(parent["job_id"], job["job_id"])
            self.assertEqual(parent["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
