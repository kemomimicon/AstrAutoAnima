import asyncio
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from astr_auto_anima_hub.image_storage import ImageStorage, StorageConfig, StorageAction


class ImageStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manager = ImageStorage(SimpleNamespace(plugin_data_dir=root / "plugin", output_dir=root / "output"), SimpleNamespace(_jobs={}))
        self.manager.idle = AsyncMock()

    def picture(self, area, name="one.png"):
        path = self.manager.root(area) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image bytes")
        os.utime(path, (time.time() - 600, time.time() - 600))
        return path

    async def test_random_style_is_exclusive_and_cleanup_requires_confirmations(self):
        picture = self.picture("random_style")
        other = self.picture("output")
        self.assertEqual(len(self.manager.inventory("output")[0]), 1)
        action = StorageAction(area="random_style")
        action.snapshot = self.manager.preview(action)["snapshot"]
        with self.assertRaises(ValueError):
            await self.manager.cleanup(action)
        action.confirmed = True
        with self.assertRaises(ValueError):
            await self.manager.cleanup(action)
        action.acknowledge_unarchived = True
        self.assertEqual((await self.manager.cleanup(action))["deleted"], 1)
        self.assertFalse(picture.exists())
        self.assertTrue(other.exists())

    async def test_changed_file_cannot_be_deleted(self):
        picture = self.picture("cache")
        action = StorageAction(area="cache", confirmed=True, acknowledge_unarchived=True)
        action.snapshot = self.manager.preview(action)["snapshot"]
        picture.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            await self.manager.cleanup(action)
        self.assertTrue(picture.exists())

    async def test_folder_selection_preserves_archive_structure_and_other_images(self):
        selected = self.picture("output", "AAA-style/style-a/a.png")
        other = self.picture("output", "AAA-style/style-b/b.png")
        nested = self.picture("output", "AAA-style/style-a/sub/c.png")
        action = StorageAction(area="output", folders=["AAA-style/style-a"],
                               destination=self.temp.name, confirmed=True)
        preview = self.manager.preview(action)
        self.assertEqual(preview["files"], ["AAA-style/style-a/a.png"])
        action.snapshot = preview["snapshot"]
        result = self.manager.archive(action)
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("AAA-style/style-a/a.png", archive.namelist())
            self.assertNotIn("AAA-style/style-b/b.png", archive.namelist())
        await self.manager.cleanup(action)
        self.assertFalse(selected.exists())
        self.assertTrue(other.exists())
        self.assertTrue(nested.exists())

    async def test_empty_unknown_and_traversal_folders_never_mean_all(self):
        self.picture("output")
        for folders in ([], ["../models"], ["missing"], ["/tmp"]):
            with self.assertRaises(ValueError):
                self.manager.preview(StorageAction(area="output", folders=folders))
        self.assertEqual(self.manager.preview(StorageAction(area="output"))["count"], 1)

    async def test_multiple_folders_and_inventory(self):
        self.picture("output", "a/one.png")
        self.picture("output", "b/two.png")
        self.picture("output", "c/three.png")
        self.assertEqual(self.manager.preview(StorageAction(area="output", folders=["a", "b"]))["count"], 2)
        output = next(a for a in self.manager.view()["areas"] if a["id"] == "output")
        self.assertEqual([f["name"] for f in output["folders"]], ["a", "b", "c"])

    async def test_archive_and_cleanup(self):
        self.picture("random_style")
        action = StorageAction(area="random_style", destination=self.temp.name, confirmed=True)
        action.snapshot = self.manager.preview(action)["snapshot"]
        archive = self.manager.archive(action)
        self.assertTrue(Path(archive["path"]).is_file())
        self.assertEqual((await self.manager.cleanup(action))["deleted"], 1)

    async def test_new_images_are_protected_and_config_persists(self):
        picture = self.picture("cache")
        os.utime(picture, None)
        self.assertEqual(self.manager.preview(StorageAction(area="cache"))["count"], 0)
        self.manager.save(StorageConfig(grouping="character"))
        self.assertEqual(self.manager.config().grouping, "character")
