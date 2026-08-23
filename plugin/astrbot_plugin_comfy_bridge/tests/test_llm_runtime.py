import unittest

from llm_runtime import (
    clean_tag_output,
    reverse_image_prompt,
    translate_chinese_prompt,
    validate_english_tags,
)
from workflow_runtime import WorkflowError


class FakeResponse:
    def __init__(self, text):
        self.completion_text = text


class FakeEvent:
    unified_msg_origin = "bot:FriendMessage:10001"


class FakeContext:
    def __init__(self, response="1girl, solo"):
        self.response = response
        self.kwargs = None

    async def get_current_chat_provider_id(self, _origin):
        return "text-provider"

    def get_config(self, **_kwargs):
        return {
            "provider_settings": {
                "default_provider_id": "default-provider",
                "default_image_caption_provider_id": "vision-provider",
            }
        }

    async def llm_generate(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse(self.response)


class LlmRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_tag_output_removes_markdown_and_newlines(self):
        self.assertEqual(
            clean_tag_output("```tags\nTags: 1girl， solo\nrain\n```"),
            "1girl, solo, rain",
        )

    def test_validation_rejects_untranslated_chinese(self):
        with self.assertRaises(WorkflowError):
            validate_english_tags("一个女孩，雨夜，拿着雨伞", label="test")

    async def test_chinese_translation_uses_current_text_provider(self):
        context = FakeContext("1girl, solo, holding umbrella")
        tags, provider = await translate_chinese_prompt(
            context, FakeEvent(), "一个女孩撑伞"
        )
        self.assertEqual(provider, "text-provider")
        self.assertEqual(tags, "1girl, solo, holding umbrella")
        self.assertNotIn("image_urls", context.kwargs)

    async def test_reverse_uses_image_caption_provider_and_image_path(self):
        context = FakeContext("1girl, solo, rainy street")
        tags, provider = await reverse_image_prompt(
            context, FakeEvent(), "/tmp/source.png"
        )
        self.assertEqual(provider, "vision-provider")
        self.assertEqual(tags, "1girl, solo, rainy street")
        self.assertEqual(context.kwargs["image_urls"], ["/tmp/source.png"])


if __name__ == "__main__":
    unittest.main()
