"""Exercise real favorite routes, owner state and per-image content identity."""
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from test_local_jobs import LocalJobsTests
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.auth import AuthPrincipal, require_reader
from astr_auto_anima_hub.prompt_favorites import list_favorites
from astr_auto_anima_hub.schemas import RemoteJobImage, RemoteJobResponse


class FavoriteAPIRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = LocalJobsTests()
        self.fixture.setUp()
        self.settings = self.fixture.settings
        self.manager = self.fixture.manager
        self.principal = AuthPrincipal(role="admin", subject="administrator")
        self.app = create_app(self.settings)
        self.app.state.remote_jobs = self.manager
        self.headers = {"Authorization": "Bearer " + self.settings.admin_token}

    def tearDown(self):
        self.fixture.tearDown()

    def job(self, *images):
        now = datetime.now(timezone.utc)
        job = RemoteJobResponse(
            id=uuid.uuid4().hex, status="succeeded", kind="random", safety_code="H",
            target_id="local", target_label="fixture", command_preview="fixture",
            images=list(images), prompt_ids=list(dict.fromkeys(i.prompt_id for i in images)),
            created_at=now, updated_at=now)
        self.manager._jobs[job.id] = job
        self.manager._owners[job.id] = self.principal.subject
        return job

    def image(self, identifier, *, prompt_id="source", addition="", safety="N", prompt="street"):
        return RemoteJobImage(id=identifier, filename=identifier + ".png", size_bytes=1,
                              sha256="a" * 64, download_url="/fixture", prompt_id=prompt_id,
                              source_prompt=prompt, user_addition=addition,
                              source_safety_code=safety)

    async def call(self, method, path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url="http://test", headers=self.headers) as client:
            return await client.request(method, path)

    async def favorite(self, job, image_id):
        return await self.call("POST", f"/api/v1/lite/jobs/{job.id}/images/{image_id}/favorite")

    async def test_cancel_commits_success_and_preserves_other_same_source_variant(self):
        job = self.job(self.image("one", addition="rain"), self.image("two", addition="sun"),
                       self.image("same-content", prompt_id="different-source", addition="rain"))
        first = await self.favorite(job, "one")
        self.assertEqual(first.status_code, 200, first.text)
        duplicate = await self.favorite(job, "same-content")
        self.assertEqual(duplicate.json()["saved_prompt_id"], first.json()["saved_prompt_id"])
        self.assertEqual(duplicate.json()["action"], "already_liked")
        second = await self.favorite(job, "two")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, ["one", "two", "same-content"])
        path = "/api/v1/lite/prompt-favorites/" + first.json()["saved_prompt_id"]
        deleted = await self.call("DELETE", path)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["removed"])
        current = self.manager.get(job.id, self.principal)
        self.assertEqual(current.liked_image_ids, ["two"])
        self.assertEqual(current.liked_prompt_ids, ["source"])
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).total, 1)
        repeated = await self.call("DELETE", path)
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["removed"])
        self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, ["two"])

    async def test_classification_survives_image_and_legacy_job_routes(self):
        for index, safety in enumerate(("N", "H", "S")):
            with self.subTest(safety=safety):
                job = self.job(self.image("image", prompt_id=f"id-{index}", safety=safety,
                                          prompt=f"different text {index}"))
                saved = await self.favorite(job, "image")
                self.assertEqual(saved.status_code, 200, saved.text)
                repeated = await self.call("POST", f"/api/v1/lite/jobs/{job.id}/likes/id-{index}")
                self.assertEqual(repeated.status_code, 200, repeated.text)
                rows = list_favorites(self.settings.prompt_favorites_path, self.principal, safety=safety)
                self.assertEqual(rows.total, 1)
                self.assertEqual(rows.items[0].safety_code, safety)

    async def test_missing_classification_is_rejected_not_inferred_from_job(self):
        job = self.job(self.image("image", safety=""))
        for path in (f"/api/v1/lite/jobs/{job.id}/images/image/favorite",
                     f"/api/v1/lite/jobs/{job.id}/likes/source"):
            result = await self.call("POST", path)
            self.assertEqual(result.status_code, 422, result.text)
            self.assertIn("分级", result.text)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).total, 0)

    async def test_duplicate_text_cannot_lower_classification(self):
        for safety in ("N", "S", "H"):
            job = self.job(self.image("image", safety=safety))
            self.assertEqual((await self.favorite(job, "image")).status_code, 200)
        rows = list_favorites(self.settings.prompt_favorites_path, self.principal)
        self.assertEqual(rows.total, 1)
        self.assertEqual(rows.items[0].safety_code, "S")

    async def test_edited_remake_snapshot_is_distinct_and_not_duplicated(self):
        job = self.job(self.image("old", prompt="red bicycle, stone wall", addition="rain"),
                       self.image("edited", prompt="stone wall, rain, blue bicycle", addition=""))
        original = await self.favorite(job, "old")
        edited = await self.favorite(job, "edited")
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertNotEqual(original.json()["saved_prompt_id"], edited.json()["saved_prompt_id"])
        rows = list_favorites(self.settings.prompt_favorites_path, self.principal)
        new = next(row for row in rows.items if row.id == edited.json()["saved_prompt_id"])
        self.assertEqual(new.prompt, "stone wall, rain, blue bicycle")
        self.assertEqual(new.user_addition, "")
        self.assertEqual((await self.favorite(job, "edited")).json()["action"], "already_liked")
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).total, 2)

    async def test_other_user_cannot_read_or_remove_owner_favorite(self):
        job = self.job(self.image("image"))
        saved = (await self.favorite(job, "image")).json()["saved_prompt_id"]
        self.app.dependency_overrides[require_reader] = lambda: AuthPrincipal(role="user", subject="other")
        self.assertEqual((await self.favorite(job, "image")).status_code, 404)
        deleted = await self.call("DELETE", "/api/v1/lite/prompt-favorites/" + saved)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.json()["removed"])
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).total, 1)

    async def test_old_history_reads_derive_owner_flags_without_database_or_record_writes(self):
        job = self.job(self.image("image"))
        missing = await self.call("GET", "/api/v1/lite/jobs")
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(self.settings.prompt_favorites_path.exists())
        await self.favorite(job, "image")
        self.manager._jobs[job.id] = job  # emulate an old record without new flags
        db_before = self.settings.prompt_favorites_path.read_bytes()
        mtime = self.settings.prompt_favorites_path.stat().st_mtime_ns
        with patch.object(self.manager, "_persist") as persist:
            response = await self.call("GET", "/api/v1/lite/jobs")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["liked_image_ids"], ["image"])
            self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, ["image"])
            other_admin = AuthPrincipal(role="admin", subject="other-admin")
            self.assertEqual(self.manager.get(job.id, other_admin).liked_image_ids, [])
            persist.assert_not_called()
        self.assertEqual(self.settings.prompt_favorites_path.read_bytes(), db_before)
        self.assertEqual(self.settings.prompt_favorites_path.stat().st_mtime_ns, mtime)

    async def test_broken_favorite_database_cannot_break_generation_history(self):
        job = self.job(self.image("image"))
        self.settings.prompt_favorites_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.prompt_favorites_path.write_bytes(b"not-a-database")
        before = self.settings.prompt_favorites_path.read_bytes()
        for path in ("/api/v1/lite/jobs", f"/api/v1/lite/jobs/{job.id}"):
            response = await self.call("GET", path)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.settings.prompt_favorites_path.read_bytes(), before)

    async def test_favorite_and_cancel_do_not_depend_on_job_record_writes(self):
        job = self.job(self.image("image"))
        original = job.model_dump()
        with patch.object(self.manager, "_persist", side_effect=OSError("task disk write denied")) as persist:
            saved = await self.favorite(job, "image")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, ["image"])
            deleted = await self.call("DELETE", "/api/v1/lite/prompt-favorites/" + saved.json()["saved_prompt_id"])
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertTrue(deleted.json()["removed"])
            self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, [])
            persist.assert_not_called()
        self.assertEqual(self.manager._jobs[job.id].model_dump(), original)
