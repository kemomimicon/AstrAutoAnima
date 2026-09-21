import unittest
from pydantic import ValidationError
from astr_auto_anima_hub.schemas import CharacterVariant, PresetWriteRequest, RemoteJobCreateRequest
from astr_auto_anima_hub.management import _preset_value
from astr_auto_anima_hub.repositories import RepositoryError


class VariantSchemaTests(unittest.TestCase):
    def test_stable_id_and_category(self):
        for bad in ("default", "x y", "../escape"):
            with self.assertRaises(ValidationError):
                CharacterVariant(id=bad, category="clothing", name="衣服", prompt="hanfu")

    def test_write_and_duplicate(self):
        variant = {"id": "hanfu", "category": "clothing", "name": "汉服", "prompt": "hanfu"}
        role = PresetWriteRequest(name="A", loras=[{"name": "a.safetensors"}], variants=[variant])
        self.assertEqual(_preset_value("character", role)["variants"][0]["id"], "hanfu")
        role.variants.append(role.variants[0])
        with self.assertRaises(RepositoryError):
            _preset_value("character", role)

    def test_legacy_omission_distinct_from_clear(self):
        self.assertIsNone(PresetWriteRequest(name="A", prompt="identity").variants)
        self.assertEqual(PresetWriteRequest(name="A", variants=[]).variants, [])

    def test_command_injection_rejected(self):
        with self.assertRaises(ValidationError):
            RemoteJobCreateRequest(target_id="private", kind="direct", character_variant="x 画风=y")


if __name__ == "__main__":
    unittest.main()
