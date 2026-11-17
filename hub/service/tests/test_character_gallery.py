import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from astr_auto_anima_hub.auth import SYSTEM_ADMIN
from astr_auto_anima_hub.character_gallery import CharacterGallery, CardWrite, router
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.remote_jobs import RemoteJobError
from astr_auto_anima_hub.repositories import RepositoryError

PLUGIN = Path(__file__).resolve().parents[3] / 'plugin/astrbot_plugin_comfy_bridge'


class Jobs:
    def __init__(self, path):
        self.path = path
        self.approved = True
    def get_image(self, job, image, principal):
        if job != 'j1' or image != 'i1' or not principal.is_admin:
            raise RemoteJobError('not owned')
        return SimpleNamespace(content_type='image/png'), self.path
    def _require_approved(self, content):
        if not self.approved:
            raise RemoteJobError('审核未通过')


class CharacterGalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(plugin_dir=PLUGIN, plugin_data_dir=self.root, admin_token='a'*32, lite_token='b'*32)
        self.settings.preset_path.write_text(json.dumps({'characters': {'Alice': {'prompt': 'alice, red hair', 'lora': None}}, 'styles': {}}), encoding='utf-8')
        self.image = self.root / 'source.png'
        self.image.write_bytes(b'approved fixture')
        self.jobs = Jobs(self.image)
        self.gallery = CharacterGallery(self.settings, self.jobs)
        self.original = self.settings.preset_path.read_bytes()

    def write(self, **kwargs):
        return self.gallery.write(CardWrite(revision=self.gallery.read()['revision'], character='Alice', **kwargs), SYSTEM_ADMIN)

    def test_read_creates_nothing_then_save_draft_publish_and_backup(self):
        self.assertEqual(self.gallery.view()['items'], [])
        self.assertFalse(self.gallery.root.exists())
        draft = self.write()
        self.assertEqual(len(draft['items']), 1)
        self.assertEqual(self.gallery.view()['items'], [])
        published = self.write(published=True)
        public = self.gallery.view()['items'][0]
        self.assertNotIn('profile', public)
        self.assertNotIn(str(self.root), json.dumps(public))
        self.assertEqual(public['id'], draft['items'][0]['id'])
        self.assertNotEqual(published['revision'], draft['revision'])
        self.assertEqual(len(list(self.gallery.root.glob('*.backup.json'))), 1)
        self.assertEqual(self.settings.preset_path.read_bytes(), self.original)

    def test_confirmed_profile_import_and_stale_rejected(self):
        view = self.write()
        p = copy.deepcopy(view['items'][0]['profile'])
        p['features']['hair'] = {'text': 'long red hair', 'source': 'user', 'confirmed': False}
        with self.assertRaises(ValueError):
            self.write(profile=p, published=True)
        p['features']['hair']['confirmed'] = True
        self.write(profile=p, published=True)
        self.assertEqual(self.gallery.view()['items'][0]['features']['hair'], 'long red hair')
        p['source']['selected_prompt'] = 'old prompt'
        with self.assertRaisesRegex(RepositoryError, '不一致'):
            self.write(profile=p)
        self.assertEqual(self.settings.preset_path.read_bytes(), self.original)

    def test_stale_revision_cannot_overwrite_and_lock_released(self):
        self.write()
        before = (self.gallery.root / 'catalog.json').read_bytes()
        with self.assertRaisesRegex(RepositoryError, '已更新'):
            self.gallery.write(CardWrite(revision='initial', character='Alice'), SYSTEM_ADMIN)
        self.assertEqual((self.gallery.root / 'catalog.json').read_bytes(), before)
        # The kernel lock is released on errors; the stable lock file can remain.
        self.write(published=True)

    def test_abandoned_lock_file_does_not_prevent_saving(self):
        self.gallery.root.mkdir()
        (self.gallery.root / 'catalog.json.write.lock').write_bytes(b'0')
        self.assertEqual(len(self.write()['items']), 1)

    def test_oversized_catalog_and_failed_replace_preserve_previous_and_remove_new_cover(self):
        self.write()
        catalog = self.gallery.root / 'catalog.json'
        before = catalog.read_bytes()
        # A limit just above the existing catalog lets the old record be read.
        with patch.object(self.gallery.core(), 'MAX_JSON_BYTES', len(before) + 10):
            with self.assertRaisesRegex(RepositoryError, '16 MiB'):
                self.write(cover_job='j1', cover_image='i1')
        self.assertEqual(catalog.read_bytes(), before)
        self.assertEqual(list(self.gallery.root.glob('*.image')), [])
        with patch.object(Path, 'replace', side_effect=OSError('disk write failure')):
            with self.assertRaises(OSError):
                self.write(cover_job='j1', cover_image='i1')
        self.assertEqual(catalog.read_bytes(), before)
        self.assertEqual(list(self.gallery.root.glob('*.image')), [])
        self.assertEqual(list(self.gallery.root.glob('*.tmp')), [])
        self.write(published=True)

    def test_cover_draft_visibility_ownership_and_audit(self):
        row = self.write(cover_job='j1', cover_image='i1')['items'][0]
        with self.assertRaises(RepositoryError):
            self.gallery.image(row['id'], False)
        self.write(published=True)
        path, mime = self.gallery.image(row['id'], False)
        self.assertEqual(path.read_bytes(), self.image.read_bytes())
        self.assertEqual(mime, 'image/png')
        before = (self.gallery.root / 'catalog.json').read_bytes()
        with self.assertRaises(RemoteJobError):
            self.write(cover_job='someone-else', cover_image='i1')
        self.assertEqual((self.gallery.root / 'catalog.json').read_bytes(), before)
        self.jobs.approved = False
        with self.assertRaises(RemoteJobError):
            self.gallery.image(row['id'], True)
        self.assertTrue(self.image.exists())

    def test_paths_and_corrupt_catalog(self):
        for name in ('../presets.json', r'..\presets.json', 'a/b', ''):
            with self.assertRaises(RepositoryError):
                self.gallery.path(name)
        self.gallery.root.mkdir()
        (self.gallery.root / 'catalog.json').write_text('{"items": null}')
        with self.assertRaises(RepositoryError):
            self.gallery.read()

    def test_http_permissions_and_structured_errors(self):
        app = FastAPI()
        app.state.settings = self.settings
        app.state.remote_jobs = self.jobs
        app.include_router(router)
        client = TestClient(app)
        admin = {'Authorization': 'Bearer ' + 'a'*32}
        reader = {'Authorization': 'Bearer ' + 'b'*32}
        self.assertEqual(client.get('/api/v1/character-gallery').status_code, 401)
        payload = {'revision':'initial', 'character':'Alice'}
        self.assertEqual(client.post('/api/v1/character-gallery', json=payload, headers=reader).status_code, 401)
        saved = client.post('/api/v1/character-gallery', json=payload, headers=admin)
        self.assertEqual(saved.status_code, 200, saved.text)
        payload.update(revision=saved.json()['revision'], cover_job='someone-else', cover_image='i1')
        self.assertEqual(client.post('/api/v1/character-gallery', json=payload, headers=admin).status_code, 422)
        self.assertEqual(client.get('/api/v1/character-gallery', headers=reader).json()['items'], [])
