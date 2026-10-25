import asyncio
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
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

    async def test_independent_cache_retention_and_primary_output_exclusion(self):
        from pydantic import ValidationError
        from astr_auto_anima_hub.image_storage import RetentionPolicy
        with self.assertRaises(ValidationError):
            RetentionPolicy(enabled=True, days=1)
        with self.assertRaises(ValueError):
            self.manager.save(StorageConfig(retention_policies={
                "output": RetentionPolicy(enabled=True, days=2)}))
        self.manager.save(StorageConfig(retention_policies={
            "remote_media": RetentionPolicy(enabled=True, days=2)}))
        self.assertFalse(self.manager.config().retention_policies.get("attachments", RetentionPolicy()).enabled)
        self.assertEqual(self.manager.config().retention_policies["remote_media"].days, 2)

    async def test_attachment_cleanup_does_not_touch_task_records(self):
        picture = self.picture("remote_media", "job-1/image.png")
        records = self.manager.root("remote_media").parent / "records" / "job-1.json"
        records.parent.mkdir(parents=True, exist_ok=True)
        records.write_text("{}", encoding="utf-8")
        action = StorageAction(area="remote_media", confirmed=True, acknowledge_unarchived=True)
        action.snapshot = self.manager.preview(action)["snapshot"]
        self.assertEqual((await self.manager.cleanup(action))["deleted"], 1)
        self.assertFalse(picture.exists())
        self.assertTrue(records.exists())

    async def test_idle_requires_exact_empty_queue_lists_before_cleanup(self):
        self.manager.settings.comfyui_url = "http://comfy.test:8188"
        # Restore production method; existing fixture skips it in filesystem-only tests.
        self.manager.idle = lambda: ImageStorage.idle(self.manager)
        picture = self.picture("cache")
        action = StorageAction(area="cache", confirmed=True, acknowledge_unarchived=True)
        action.snapshot = self.manager.preview(action)["snapshot"]
        invalid = [None, {}, {"queue_running": None, "queue_pending": None},
                   {"queue_running": {}, "queue_pending": []},
                   {"queue_running": "", "queue_pending": []},
                   {"queue_running": [], "queue_pending": ["pending"]}]
        for queue in invalid:
            with self.subTest(queue=queue):
                client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=queue)))
                with patch("httpx.AsyncClient", return_value=client):
                    with self.assertRaises(ValueError):
                        await self.manager.cleanup(action)
                self.assertTrue(picture.exists())
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"queue_running": [], "queue_pending": []})))
        with patch("httpx.AsyncClient", return_value=client):
            await self.manager.idle()
        self.assertTrue(picture.exists())

    async def test_idle_rejects_unknown_plugin_and_hub_states(self):
        self.manager.settings.comfyui_url = "http://comfy.test:8188"
        records = self.manager.settings.plugin_data_dir / "job_store" / "jobs"
        records.mkdir(parents=True)
        path = records / "job.json"
        for value in ({}, [], {"status": None}, {"status": "pending"}, {"status": "running"}):
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(plugin=value), self.assertRaises(ValueError):
                await ImageStorage.idle(self.manager)
        path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        for state in (None, "unknown", "queued", "running"):
            self.manager.jobs._jobs = {"job": SimpleNamespace(status=state)}
            with self.subTest(hub=state), self.assertRaises(ValueError):
                await ImageStorage.idle(self.manager)
        self.manager.jobs._jobs = {"job": SimpleNamespace(status="succeeded")}
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"queue_running": [], "queue_pending": []})))
        with patch("httpx.AsyncClient", return_value=client):
            await ImageStorage.idle(self.manager)

    async def test_idle_rejects_non_directory_job_store(self):
        records = self.manager.settings.plugin_data_dir / "job_store" / "jobs"
        records.parent.mkdir(parents=True)
        records.write_text("not-a-job-directory", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "目录类型异常"):
            await ImageStorage.idle(self.manager)
