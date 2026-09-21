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
    configure_detail_repair_workflow,
    configure_hq_workflow,
    configure_refine_workflow,
    configure_seedvr2_workflow,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = PROJECT_ROOT / "astrbot_plugin_comfy_bridge"


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
                "detail_repair_anima_v1",
                "hq_txt2img_anima_v1",
                "quick_txt2img_v1",
                "refine_existing_v1",
                "reverse_anime_v1",
                "seedvr2_refine_v1",
            ),
        )

    def test_detail_repair_profile_defaults_to_hands_and_feet(self):
        detail = self.registry.resolve("detail_repair_anima_v1")
        self.assertEqual(detail.profile("")[0], "balanced")
        self.assertEqual(detail.capability["detailer_default"], ["hands", "feet"])

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
                PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_HQ_Txt2Img_Beta_api.json",
            ),
            (
                "refine_existing_v1",
                PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_Refine_Existing_Beta_api.json",
            ),
            (
                "detail_repair_anima_v1",
                PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_Detail_Repair_Beta_api.json",
            ),
            (
                "seedvr2_refine_v1",
                PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_SeedVR2_Refine_Beta_api.json",
            ),
        )
        for workflow_id, path in pairs:
            with self.subTest(workflow=workflow_id):
                validate_workflow_nodes(
                    load_json(path), self.registry.resolve(workflow_id)
                )


class HqRefineConfigurationTests(unittest.TestCase):
    def test_detail_repair_chains_enabled_parts_and_skips_face(self):
        workflow = load_json(
            PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_Detail_Repair_Beta_api.json"
        )
        workflow["52"]["inputs"]["model"] = ["900001", 0]
        workflow["11"]["inputs"]["clip"] = ["900001", 1]
        result = configure_detail_repair_workflow(
            workflow,
            image_name="incoming/source.png",
            image_node_id="1",
            output_node_id="9",
            positive_node_id="11",
            negative_node_id="12",
            face_node_id="52",
            hand_node_id="62",
            foot_node_id="72",
            profile={
                "detailer": {
                    "hands": {"denoise": 0.35},
                    "feet": {"denoise": 0.32},
                }
            },
            seed=123,
            repair_face=False,
            repair_hands=True,
            repair_feet=True,
        )
        self.assertNotIn("52", workflow)
        self.assertEqual(workflow["62"]["inputs"]["image"], ["1", 0])
        self.assertEqual(workflow["72"]["inputs"]["image"], ["62", 0])
        self.assertEqual(workflow["9"]["inputs"]["images"], ["72", 0])
        self.assertEqual(workflow["62"]["inputs"]["model"], ["900001", 0])
        self.assertEqual([row["part"] for row in result["detailer"]], ["hands", "feet"])

    def test_hq_profile_configures_both_stages_and_syncs_lora_chain(self):
        workflow = load_json(
            PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_HQ_Txt2Img_Beta_api.json"
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
            PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_Refine_Existing_Beta_api.json"
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
            PROJECT_ROOT.parent / "comfyui/workflows" / "Anima_Refine_Existing_Beta_api.json"
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
            PROJECT_ROOT.parent / "comfyui/workflows/Anima_SeedVR2_Refine_Beta_api.json"
        )
        # Synthetic legacy graph exercises compatibility without distributing an old pack.
        workflow['4']['class_type'] = 'SeedVR2TilingUpscaler'
        workflow['4']['inputs'] = {'image': ['1', 0], 'dit': ['2', 0], 'vae': ['3', 0], 'seed': 0,
                                  'new_resolution': 2048, 'tile_width': 512, 'tile_height': 512,
                                  'tile_padding': 32, 'tile_upscale_resolution': 1024,
                                  'mask_blur': 0, 'anti_aliasing_strength': 0,
                                  'tiling_strategy': 'uniform', 'blending_method': 'linear',
                                  'color_correction': 'lab', 'resolution_target': 'longest', 'tile_batch_size': 1}
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

    def test_seedvr2_native_keeps_long_edge_and_ignores_legacy_tile_fields(self):
        workflow = load_json(PROJECT_ROOT.parent / "comfyui/workflows/Anima_SeedVR2_Refine_Beta_api.json")
        result = configure_seedvr2_workflow(
            workflow, image_name="source.png", image_node_id="1", upscaler_node_id="4",
            profile={"enhance": {"target_resolution": 3072, "tile_width": 1024}}, seed=2**32+7)
        self.assertEqual(workflow["4"]["inputs"]["resolution"], 3072)
        self.assertEqual(workflow["4"]["inputs"]["max_resolution"], 3072)
        self.assertEqual(workflow["4"]["inputs"]["seed"], 7)
        self.assertNotIn("tile_width", workflow["4"]["inputs"])
        self.assertFalse(result["tile"])
        self.assertTrue(workflow["3"]["inputs"]["decode_tiled"])
        with self.assertRaises(WorkflowError):
            configure_seedvr2_workflow(workflow, image_name="a.png", image_node_id="1",
                upscaler_node_id="4", profile={"enhance": {"target_resolution": 10000}}, seed=0)


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
