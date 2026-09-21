import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from astr_auto_anima_hub.auth import SYSTEM_ADMIN
from astr_auto_anima_hub.repositories import RepositoryError
from astr_auto_anima_hub.style_gallery import StyleGallery, GalleryConfig, GalleryUpdate, GalleryGenerate


class FakeJobs:
    def __init__(self, root):
        self.calls = []
        self.approvals = 0
        self.pending = False
        self.source = root / 'ordinary.png'
        self.source.write_bytes(b'approved test bytes')

    def targets(self, principal):
        return SimpleNamespace(targets=[SimpleNamespace(id='private')])

    def create(self, request, principal):
        self.calls.append(request)
        self.job = SimpleNamespace(id=str(len(self.calls)), status='running' if self.pending else 'succeeded',
                                   images=[SimpleNamespace(id='image')], message='')
        return self.job

    def get(self, job, principal):
        return self.job

    def get_image(self, job, image, principal):
        return SimpleNamespace(content_type='image/png'), self.source

    def _require_approved(self, content):
        self.approvals += 1


class GalleryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        presets = self.root / 'presets.json'
        presets.write_text(json.dumps({'styles': {'ink': {'loras': [], 'prompt': 'ink'}},
                                     'characters': {'A': {'lora': {'name': 'a.safetensors'}, 'prompt': 'identity'}}}), encoding='utf-8')
        self.jobs = FakeJobs(self.root)
        self.gallery = StyleGallery(SimpleNamespace(plugin_data_dir=self.root, preset_path=presets), self.jobs)

    async def asyncTearDown(self):
        await self.gallery.shutdown()
        self.temp.cleanup()

    async def configured(self):
        view = self.gallery.view(True)
        return await self.gallery.update(GalleryUpdate(revision=view['revision'], config=GalleryConfig(
            prompts=['scene 1', 'scene 2', 'scene 3', 'scene 4'], character_text='model text', target_id='private')))

    async def test_empty_slots_and_warning_and_generation_blocked(self):
        view = self.gallery.view(True)
        from astr_auto_anima_hub.gallery_defaults import PROMPTS
        self.assertEqual(view['config']['prompts'], PROMPTS)
        self.assertTrue((self.root / 'style_gallery' / '请勿手动清理.txt').is_file())
        with self.assertRaises(RepositoryError):
            await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        self.assertEqual(self.jobs.calls, [])

    async def test_four_jobs_audited_no_im_and_precise_cleanup(self):
        view = await self.configured()
        await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await self.gallery.task
        view = self.gallery.view(True)
        self.assertEqual(len(self.jobs.calls), 4)
        self.assertTrue(all(not call.deliver_to_im and call.style == 'ink' for call in self.jobs.calls))
        self.assertEqual([c.prompt for c in self.jobs.calls], [f'model text, scene {i}' for i in range(1, 5)])
        self.assertTrue(all(s['status'] == 'succeeded' for s in view['items'][0]['slots']))
        image_id = view['items'][0]['slots'][0]['url'].split('/')[-1]
        self.gallery.image(image_id)
        self.assertEqual(self.jobs.approvals, 5)
        changed = GalleryConfig(**{**view['config'], 'character_text': 'new model'})
        with self.assertRaises(RepositoryError):
            await self.gallery.update(GalleryUpdate(revision=view['revision'], config=changed))
        await self.gallery.update(GalleryUpdate(revision=view['revision'], config=changed, confirm_clear=True))
        self.assertTrue(self.jobs.source.exists())
        self.assertEqual(list((self.root / 'style_gallery').glob('*.image')), [])
        with self.assertRaises(RepositoryError):
            self.gallery.image(image_id)

    async def test_old_running_job_cannot_republish_after_model_change(self):
        view = await self.configured()
        self.jobs.pending = True
        await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await asyncio.sleep(0)
        view = self.gallery.view(True)
        with self.assertRaises(RepositoryError):
            await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await self.gallery.update(GalleryUpdate(revision=view['revision'], config=GalleryConfig(), confirm_clear=True))
        self.jobs.job.status = 'succeeded'
        await self.gallery.task
        self.assertEqual(self.gallery.view()['items'], [])
        self.assertEqual(list((self.root / 'style_gallery').glob('*.image')), [])
        self.assertEqual(len(self.jobs.calls), 1)

    async def test_manifest_traversal_aborts_deletion(self):
        bad = {'items': [{'slots': [{'file': '../ordinary.png'}]}]}
        with self.assertRaises(RepositoryError):
            self.gallery._delete_owned(bad)
        self.assertTrue(self.jobs.source.exists())

    async def test_single_slot_replaces_only_after_success(self):
        view = await self.configured()
        await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await self.gallery.task
        old = [s['file'] for s in self.gallery._read()['items'][0]['slots']]
        view = self.gallery.view(True)
        await self.gallery.generate(GalleryGenerate(revision=view['revision'], styles=['ink'], slot_index=2), SYSTEM_ADMIN)
        self.assertTrue(all(self.gallery._path(f).exists() for f in old))
        await self.gallery.task
        new = [s['file'] for s in self.gallery._read()['items'][0]['slots']]
        self.assertEqual(len(self.jobs.calls), 5)
        self.assertNotEqual(new[2], old[2])
        self.assertFalse(self.gallery._path(old[2]).exists())
        self.assertEqual(new[:2] + new[3:], old[:2] + old[3:])

    async def test_single_slot_failure_keeps_old_image(self):
        view = await self.configured()
        await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await self.gallery.task
        old = self.gallery._read()['items'][0]['slots'][1]['file']
        def reject(content):
            raise RepositoryError('audit unavailable')
        self.jobs._require_approved = reject
        await self.gallery.generate(GalleryGenerate(revision=self.gallery.view(True)['revision'], styles=['ink'], slot_index=1), SYSTEM_ADMIN)
        await self.gallery.task
        self.assertEqual(self.gallery._read()['items'][0]['slots'][1]['file'], old)
        self.assertTrue(self.gallery._path(old).is_file())

    async def test_revision_conflict(self):
        await self.configured()
        with self.assertRaises(RepositoryError):
            await self.gallery.update(GalleryUpdate(revision='initial', config=GalleryConfig()))

    async def test_failure_does_not_publish(self):
        view = await self.configured()
        def blocked(content):
            raise RepositoryError('audit blocked')
        self.jobs._require_approved = blocked
        await self.gallery.generate(GalleryGenerate(revision=view['revision']), SYSTEM_ADMIN)
        await self.gallery.task
        self.assertTrue(all(s['status'] == 'failed' and 'url' not in s for s in self.gallery.view()['items'][0]['slots']))


if __name__ == '__main__':
    unittest.main()
