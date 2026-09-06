import unittest

from astrbot_plugin_comfy_bridge.agent_tools_runtime import (
    build_agent_generation_request,
    list_agent_presets,
)
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class AgentGenerationDefaultsTests(unittest.TestCase):
    def test_agent_defaults_are_independent_and_complete(self):
        prompt, options, workflow_type, profile = build_agent_generation_request(
            {
                "agent_tool_default_character": "铃兰",
                "agent_tool_default_style": "防冻液画风",
                "agent_tool_default_ratio": "9:16",
                "agent_tool_default_quality": "hq_beauty",
                "agent_tool_default_sampler": "2m_sde_gpu",
                "agent_tool_default_scheduler": "karras",
                "agent_tool_default_steps": 30,
                "agent_tool_default_cfg": 6,
            },
            prompt="1girl, solo, rainy night",
        )
        self.assertEqual(prompt, "1girl, solo, rainy night")
        self.assertEqual(options["character"], "铃兰")
        self.assertEqual(options["style"], "防冻液画风")
        self.assertEqual(options["ratio"], "9:16")
        self.assertEqual(options["sampler_preset"], "2m_sde_gpu")
        self.assertEqual(options["scheduler"], "karras")
        self.assertEqual(options["sampler_steps"], 30)
        self.assertEqual(options["sampler_cfg"], 6.0)
        self.assertEqual(workflow_type, "hq_txt2img_anima_v1")
        self.assertEqual(profile, "beauty")

    def test_explicit_values_override_defaults(self):
        _, options, workflow_type, profile = build_agent_generation_request(
            {
                "agent_tool_default_character": "铃兰",
                "agent_tool_default_style": "默认画风",
                "agent_tool_default_ratio": "2:3",
                "agent_tool_default_quality": "quick",
                "agent_tool_default_sampler": "original",
                "agent_tool_default_scheduler": "normal",
            },
            prompt="1girl, solo",
            ratio="16:9",
            character="none",
            style="其他画风",
            quality="hq_stable",
            sampler="2m",
            scheduler="exponential",
            steps=24,
            cfg=5.5,
        )
        self.assertNotIn("character", options)
        self.assertEqual(options["style"], "其他画风")
        self.assertEqual(options["ratio"], "16:9")
        self.assertEqual(options["sampler_preset"], "2m")
        self.assertEqual(options["scheduler"], "exponential")
        self.assertEqual(options["sampler_steps"], 24)
        self.assertEqual(options["sampler_cfg"], 5.5)
        self.assertEqual(workflow_type, "hq_txt2img_anima_v1")
        self.assertEqual(profile, "stable")

    def test_parameter_override_can_be_forced_off(self):
        _, options, workflow_type, profile = build_agent_generation_request(
            {
                "agent_tool_allow_parameter_override": False,
                "agent_tool_default_character": "默认角色",
                "agent_tool_default_style": "默认画风",
                "agent_tool_default_ratio": "3:4",
                "agent_tool_default_quality": "quick",
                "agent_tool_default_sampler": "original",
                "agent_tool_default_scheduler": "normal",
            },
            prompt="1girl, solo",
            character="其他角色",
            style="其他画风",
            ratio="16:9",
            quality="hq_beauty",
            sampler="2m_sde",
            scheduler="karras",
            steps=40,
            cfg=8,
        )
        self.assertEqual(options["character"], "默认角色")
        self.assertEqual(options["style"], "默认画风")
        self.assertEqual(options["ratio"], "3:4")
        self.assertEqual(options["sampler_preset"], "original")
        self.assertEqual(options["scheduler"], "normal")
        self.assertNotIn("sampler_steps", options)
        self.assertNotIn("sampler_cfg", options)
        self.assertEqual((workflow_type, profile), ("quick_txt2img_v1", ""))

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(WorkflowError, "比例无效"):
            build_agent_generation_request({}, prompt="1girl", ratio="7:5")
        with self.assertRaisesRegex(WorkflowError, "步数"):
            build_agent_generation_request({}, prompt="1girl", steps=151)


class AgentPresetQueryTests(unittest.TestCase):
    def test_query_filters_names_without_exposing_lora_data(self):
        presets = {
            "characters": {
                "铃兰": {"lora": {"name": "private.safetensors"}},
                "犬升麻": {"prompt": "private tags"},
            },
            "styles": {"防冻液画风": {"loras": [{"name": "style.safetensors"}]}},
        }
        result = list_agent_presets(
            presets, category="character", query="铃", limit=10
        )
        self.assertEqual(result, {"characters": ["铃兰"]})
        self.assertNotIn("private.safetensors", str(result))


if __name__ == "__main__":
    unittest.main()
