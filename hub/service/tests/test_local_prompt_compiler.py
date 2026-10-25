from __future__ import annotations

import unittest

from astr_auto_anima_hub.local_prompt_compiler import order_tags


class LocalPromptCompilerTests(unittest.TestCase):
    def test_adult_subject_counts_precede_presets_and_general_tags(self):
        for subject in ("1woman", "1man", "2women", "3men", "multiple women", "multiple men"):
            with self.subTest(subject=subject):
                self.assertEqual(
                    order_tags(f"watercolor, silver hair, {subject}, solo, mountain"),
                    f"{subject}, solo, watercolor, silver hair, mountain",
                )

    def test_count_relative_order_remains_stable(self):
        self.assertEqual(
            order_tags("mountain, solo, 1man, 2women, 1girl, multiple boys, moon"),
            "solo, 1man, 2women, 1girl, multiple boys, mountain, moon",
        )

    def test_case_and_underscore_dedup_preserve_first_spelling(self):
        self.assertEqual(
            order_tags("mountain, 1MAN, 1man, 2_women, 2 women, SOLO, solo"),
            "1MAN, 2_women, SOLO, mountain",
        )

    def test_existing_bucket_order_and_counts_unchanged(self):
        self.assertEqual(
            order_tags(
                "watercolor, artist:example, copyright:series, character:example, "
                "1girl, 2boys, 3people, 4others, multiple girls, solo, best quality, moon"
            ),
            "best quality, 1girl, 2boys, 3people, 4others, multiple girls, solo, "
            "character:example, copyright:series, artist:example, watercolor, moon",
        )

    def test_standalone_gender_words_remain_general_tags(self):
        self.assertEqual(
            order_tags("woman, portrait, 1girl, solo, man"),
            "1girl, solo, woman, portrait, man",
        )


if __name__ == "__main__":
    unittest.main()
