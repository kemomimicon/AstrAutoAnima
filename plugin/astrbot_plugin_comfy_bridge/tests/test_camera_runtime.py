import unittest

from camera_runtime import compile_camera_options
from preset_runtime import parse_generation_directives
from workflow_runtime import WorkflowError


class CameraRuntimeTests(unittest.TestCase):
    def test_normal_camera_is_prompt_only(self):
        plan = compile_camera_options(
            {
                "camera_distance": "cowboy",
                "camera_yaw": "three_quarter",
                "camera_pitch": "slight_low",
                "camera_lens": "wide",
                "camera_roll": "dutch",
            },
            extreme_lora_name="camera.safetensors",
        )
        self.assertIn("cowboy shot", plan.prompt)
        self.assertIn("slightly from below", plan.prompt)
        self.assertIsNone(plan.lora)

    def test_extreme_pitch_uses_dit_only_lora(self):
        plan = compile_camera_options(
            {"camera_pitch": "extreme_high", "camera_extreme_lora": True},
            extreme_lora_name="anima_lora/camera/extreme.safetensors",
            extreme_lora_strength=0.7,
        )
        self.assertIn("from above", plan.prompt)
        self.assertEqual(plan.lora["strength_model"], 0.7)
        self.assertEqual(plan.lora["strength_clip"], 0.0)

    def test_extreme_lora_is_opt_in(self):
        for flag in (None, False, "false"):
            plan = compile_camera_options(
                {"camera_pitch": "extreme_low", "camera_extreme_lora": flag},
                extreme_lora_name="camera.safetensors")
            self.assertIsNone(plan.lora)
            self.assertTrue(plan.prompt)
        self.assertIsNone(compile_camera_options(
            {"camera_pitch": "eye", "camera_extreme_lora": True},
            extreme_lora_name="camera.safetensors").lora)

    def test_new_switch_directives(self):
        prompt, options = parse_generation_directives("极限辅助=开启 修复后放大=关闭 solo")
        self.assertEqual(prompt, "solo")
        self.assertTrue(options["camera_extreme_lora"])
        self.assertFalse(options["detail_upscale"])

    def test_unknown_value_fails(self):
        with self.assertRaises(WorkflowError):
            compile_camera_options({"camera_pitch": "upside_down"})

    def test_generation_directives_parse_camera_and_detail_switches(self):
        prompt, options = parse_generation_directives(
            "俯仰机位=extreme_low 镜头效果=wide 修手=开启 修脚=关闭 修脸=关闭 solo"
        )
        self.assertEqual(prompt, "solo")
        self.assertEqual(options["camera_pitch"], "extreme_low")
        self.assertEqual(options["camera_lens"], "wide")
        self.assertTrue(options["detail_hands"])
        self.assertFalse(options["detail_feet"])


if __name__ == "__main__":
    unittest.main()
