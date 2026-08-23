from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astr_auto_anima_hub.repositories import (
    file_revision,
    list_presets,
    list_prompts,
)


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prompt_path = self.root / "anima_random_prompt_pool.json"
        self.preset_path = self.root / "presets.json"
        self.prompt_path.write_text(
            json.dumps(
                {
                    "prompts": [
                        {
                            "id": "discord-0002",
                            "name": "sun",
                            "prompt": "1girl, solo, sunny beach",
                            "source_code": "D",
                            "safety_code": "N",
                            "enabled": False,
                        },
                        {
                            "id": "discord-0001",
                            "name": "rain",
                            "prompt": "1girl, solo, rainy street",
                            "source_code": "D",
                            "safety_code": "N",
                            "enabled": True,
                            "categories": ["rain"],
                        },
                        {
                            "id": "codex-0001",
                            "name": "night",
                            "prompt": "1girl, solo, night city",
                            "source_code": "C",
                            "safety_code": "H",
                            "enabled": True,
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.preset_path.write_text(
            json.dumps(
                {
                    "styles": {
                        "ink": {
                            "prompt": "ink style",
                            "match": ["@ink"],
                            "loras": [{"name": "ink.safetensors"}],
                        }
                    },
                    "characters": {
                        "hero": {"prompt": "hero tag", "lora": None},
                        "wolf": {
                            "prompt": "wolf tag",
                            "lora": {"name": "wolf.safetensors"},
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_filters_and_sorts_prompts(self) -> None:
        page = list_prompts(
            self.prompt_path,
            source="D",
            safety="N",
            query="rain",
            enabled=True,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].id, "discord-0001")
        self.assertTrue(page.revision)

    def test_paginates(self) -> None:
        first = list_prompts(self.prompt_path, page=1, page_size=2)
        second = list_prompts(self.prompt_path, page=2, page_size=2)
        self.assertEqual(first.total, 3)
        self.assertEqual(first.pages, 2)
        self.assertEqual(len(first.items), 2)
        self.assertEqual(len(second.items), 1)

    def test_lists_presets(self) -> None:
        result = list_presets(self.preset_path)
        self.assertEqual([item.name for item in result.styles], ["ink"])
        self.assertEqual([item.name for item in result.characters], ["hero", "wolf"])
        self.assertTrue(result.characters[0].text_only)
        self.assertFalse(result.characters[1].text_only)

    def test_revision_changes_with_content(self) -> None:
        before = file_revision(self.prompt_path, "prompts")
        self.prompt_path.write_text('{"prompts": []}', encoding="utf-8")
        after = file_revision(self.prompt_path, "prompts")
        self.assertNotEqual(before.revision, after.revision)


if __name__ == "__main__":
    unittest.main()

