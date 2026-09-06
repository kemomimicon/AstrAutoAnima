from __future__ import annotations

import json
from pathlib import Path

from astr_auto_anima_hub.character_dictionary import search_character_dictionary


def test_missing_dictionary_is_reported_without_error(tmp_path: Path) -> None:
    result = search_character_dictionary(tmp_path / "missing.json", query="初音")
    assert result.available is False
    assert result.items == []


def test_search_prefers_exact_alias_and_builds_modes(tmp_path: Path) -> None:
    path = tmp_path / "characters.json"
    path.write_text(
        json.dumps(
            {
                "characters": [
                    {
                        "tag": "hatsune_miku",
                        "aliases": ["初音未来", "初音"],
                        "copyright": ["vocaloid"],
                        "gender": ["1girl"],
                        "appearance": ["aqua hair", "twintails"],
                        "post_count": 100,
                    },
                    {
                        "tag": "other_miku",
                        "aliases": ["未来同学"],
                        "post_count": 10,
                    },
                    {
                        "tag": "hatsune_miku_(snow_princess)",
                        "base_tag": "hatsune_miku",
                        "is_variant": True,
                        "aliases": ["雪未来（雪公主）", "初音未来"],
                        "post_count": 1000,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    result = search_character_dictionary(path, query="初音未来")
    assert result.available is True
    assert result.total == 2
    item = result.items[0]
    assert item.tag == "hatsune_miku"
    assert item.chinese_names == ["初音未来", "初音"]
    assert item.weak_prompt == "hatsune_miku, vocaloid"
    assert item.strong_prompt.endswith("1girl, aqua hair, twintails")

    variant = search_character_dictionary(path, query="雪未来（雪公主）")
    assert variant.items[0].tag == "hatsune_miku_(snow_princess)"
