import json
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.preset_queue import PresetQueue, PresetSubmission
from astr_auto_anima_hub.repositories import list_presets
from astrbot_plugin_comfy_bridge.preset_runtime import load_presets, save_presets
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class ManualQueue(PresetQueue):
    def start(self):
        pass


class PresetSubmissions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.path = root / 'presets.json'
        self.path.write_text(json.dumps({'characters': {'old': {'prompt': 'old text'}}, 'styles': {}}), encoding='utf-8')
        self.settings = Settings(plugin_data_dir=root / 'data', preset_override=self.path)
        self.queue = ManualQueue(self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def request(self, name='new', prompt='new text', **kwargs):
        return PresetSubmission(request_id=uuid.uuid4().hex, action='create', kind='character',
                                value={'name': name, 'prompt': prompt}, **kwargs)

    def submit(self, request):
        self.assertEqual(self.queue.submit(request, 'admin')['status'], 'queued')
        self.queue.drain_once()
        return self.queue.get(request.request_id)

    def test_unrelated_write_does_not_block_queued_edit(self):
        original = list_presets(self.path).characters[0]
        request = PresetSubmission(request_id=uuid.uuid4().hex, action='update', kind='character',
            original_name='old', expected=original, value={'name': 'old', 'prompt': 'desired'})
        self.queue.submit(request, 'admin')
        doc = load_presets(self.path)
        doc['characters']['unrelated'] = {'prompt': 'other text'}
        save_presets(self.path, doc)
        self.queue.drain_once()
        self.assertEqual(self.queue.get(request.request_id)['status'], 'succeeded')
        data = load_presets(self.path)
        self.assertEqual(data['characters']['old']['prompt'], 'desired')
        self.assertIn('unrelated', data['characters'])

    def test_real_same_item_conflict_preserves_both_submitted_and_live_content(self):
        original = list_presets(self.path).characters[0]
        request = PresetSubmission(request_id=uuid.uuid4().hex, action='update', kind='character',
            original_name='old', expected=original, value={'name': 'old', 'prompt': 'draft'})
        self.queue.submit(request, 'admin')
        doc = load_presets(self.path)
        doc['characters']['old']['prompt'] = 'someone else'
        save_presets(self.path, doc)
        self.queue.drain_once()
        self.assertEqual(self.queue.get(request.request_id)['status'], 'conflict')
        self.assertEqual(load_presets(self.path)['characters']['old']['prompt'], 'someone else')
        with closing(self.queue.connect()) as db:
            self.assertIn('draft', db.execute('SELECT payload FROM submissions').fetchone()[0])

    def test_restart_idempotent_retry_does_not_duplicate_backup(self):
        request = self.request()
        self.queue.submit(request, 'admin')
        self.queue = ManualQueue(self.settings)
        self.queue.drain_once()
        before = list(self.settings.backup_dir.rglob('*.json'))
        result = self.queue.submit(request, 'admin')
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(self.queue.drain_once())
        self.assertEqual(before, list(self.settings.backup_dir.rglob('*.json')))

    def test_qq_stale_whole_file_does_not_erase_hub_update(self):
        stale = load_presets(self.path)
        self.assertEqual(self.submit(self.request())['status'], 'succeeded')
        stale['characters']['old']['prompt'] = 'qq changed'
        save_presets(self.path, stale)
        current = load_presets(self.path)
        self.assertEqual(current['characters']['new']['prompt'], 'new text')
        self.assertEqual(current['characters']['old']['prompt'], 'qq changed')

    def test_qq_same_item_conflict_not_silent_overwrite(self):
        first, second = load_presets(self.path), load_presets(self.path)
        first['characters']['old']['prompt'] = 'one'
        second['characters']['old']['prompt'] = 'two'
        save_presets(self.path, first)
        with self.assertRaises(WorkflowError):
            save_presets(self.path, second)

    def test_id_reuse_cannot_change_request(self):
        request = self.request()
        self.submit(request)
        changed = request.model_copy(update={'action': 'delete'})
        with self.assertRaisesRegex(Exception, '编号'):
            self.queue.submit(changed, 'admin')

    def test_create_and_update_base_model_outfit_through_queue(self):
        variant = {'id': 'dress', 'category': 'clothing', 'name': '裙装',
                   'prompt': 'base_character, dress'}
        request = PresetSubmission(request_id=uuid.uuid4().hex, action='create', kind='character',
            value={'name': 'Base', 'prompt': 'base_character, uniform', 'loras': [], 'variants': [variant]})
        self.assertEqual(self.submit(request)['status'], 'succeeded')
        original = next(row for row in list_presets(self.path).characters if row.name == 'Base')
        self.assertTrue(original.text_only)
        self.assertEqual(original.variants[0].id, 'dress')
        update = PresetSubmission(request_id=uuid.uuid4().hex, action='update', kind='character',
            original_name='Base', expected=original,
            value={'name': 'Base', 'prompt': 'base_character, coat', 'loras': []})
        self.assertEqual(self.submit(update)['status'], 'succeeded')
        row = load_presets(self.path)['characters']['Base']
        self.assertIsNone(row['lora'])
        self.assertEqual(row['variants'][0]['prompt'], 'base_character, dress')

    def test_cross_process_lock_modules_match(self):
        root = Path(__file__).parents[3]
        self.assertEqual((root / 'plugin/astrbot_plugin_comfy_bridge/preset_lock.py').read_bytes(),
                         (root / 'hub/service/src/astr_auto_anima_hub/preset_lock.py').read_bytes())


class PresetSubmissionAPI(unittest.IsolatedAsyncioTestCase):
    async def test_admin_enqueue_status_and_reject_anonymous(self):
        import httpx
        from dataclasses import replace
        from astr_auto_anima_hub.app import create_app
        fixture = PresetSubmissions()
        fixture.setUp()
        try:
            settings = replace(fixture.settings, admin_token='a' * 32)
            app = create_app(settings)
            app.state.preset_queue = fixture.queue
            request = fixture.request()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                url = '/api/v1/admin/preset-submissions'
                rejected = await client.post(url, json=request.model_dump())
                self.assertEqual(rejected.status_code, 401)
                headers = {'Authorization': 'Bearer ' + settings.admin_token}
                accepted = await client.post(url, json=request.model_dump(), headers=headers)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                self.assertEqual(accepted.json()['status'], 'queued')
                fixture.queue.drain_once()
                state = await client.get(url + '/' + request.request_id, headers=headers)
                self.assertEqual(state.json()['status'], 'succeeded')
                repeated = await client.post(url, json=request.model_dump(), headers=headers)
                self.assertEqual(repeated.json()['status'], 'succeeded')
        finally:
            fixture.tearDown()
