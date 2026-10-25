import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import replace

from test_favorites_api_regressions import FavoriteAPIRegressions
from astr_auto_anima_hub.prompt_favorites import list_favorites


class ActualImagePrompts(FavoriteAPIRegressions):
    async def test_real_qq_action_accepts_direct_compiled_prompt_and_deduplicates(self):
        from astr_auto_anima_hub.qq_image_actions import handle_qq_action
        from astr_auto_anima_hub.auth import AuthPrincipal
        self.settings = replace(self.settings, legacy_lite_qq='123456789')
        job = self.job(self.image('image'))
        self.evidence(job)
        tickets = self.settings.hub_state_dir / 'qq_image_actions'
        tickets.mkdir(parents=True)
        actions = []
        for _ in range(2):
            token = uuid.uuid4().hex
            (tickets / (token + '.json')).write_text(json.dumps({
                'qq': '123456789', 'action': 'favorite', 'job_id': 'job_bridge',
                'asset_id': 'second', 'expires_at': time.time() + 60}), encoding='utf-8')
            actions.append(handle_qq_action(self.settings, None, SimpleNamespace(refresh_likes=Mock()), token))
        rows = list_favorites(self.settings.prompt_favorites_path,
                              AuthPrincipal(role='user', subject='legacy-owner', qq='123456789'))
        self.assertEqual(rows.total, 1)
        self.assertEqual(rows.items[0].prompt, 'two, moon, character')
        self.assertIn('已经收藏', actions[1]['message'])

    def remote(self):
        self.settings = replace(self.settings, execution_mode='remote')
        self.app.state.settings = self.settings
        # create_app closes over settings, so replace the fixture app as well.
        from astr_auto_anima_hub.app import create_app
        self.app = create_app(self.settings)
        self.app.state.remote_jobs = self.manager

    def evidence(self, job):
        store = self.settings.plugin_data_dir / 'job_store'
        for folder in ['jobs', 'assets']:
            (store / folder).mkdir(parents=True, exist_ok=True)
        source = {'job_id': 'job_bridge', 'input': {
            'compiled_prompt': 'compiled fallback', 'batch_prompts': ['one, rain, style', 'two, moon, character'],
            'negative': 'bad hands'}, 'result': {'assets': ['first', 'second']}}
        (store / 'jobs/job_bridge.json').write_text(json.dumps(source), encoding='utf-8')
        for i, asset in enumerate(['first', 'second']):
            (store / f'assets/{asset}.json').write_text(json.dumps({
                'asset_id': asset, 'job_id': 'job_bridge', 'type': 'result',
                'sha256': ('a' if i == 0 else 'b') * 64, 'path': '/image/already/deleted.png'}), encoding='utf-8')
        job.bridge_job_ids = ['job_bridge']

    async def test_no_library_id_lookup_and_favorite_actual_second_image_after_cleanup(self):
        self.remote()
        image = self.image('second', prompt_id='', prompt='', safety='')
        image.sha256 = 'b' * 64
        job = self.job(image)
        self.evidence(job)
        response = await self.call('GET', f'/api/v1/lite/jobs/{job.id}/images/second/prompt')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['positive'], 'two, moon, character')
        self.assertEqual(response.json()['negative'], 'bad hands')
        saved = await self.favorite(job, 'second')
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual((await self.favorite(job, 'second')).json()['action'], 'already_liked')
        rows = list_favorites(self.settings.prompt_favorites_path, self.principal)
        self.assertEqual(rows.items[0].prompt, 'two, moon, character')
        self.assertEqual(rows.items[0].safety_code, 'S')
        self.assertFalse(list(self.settings.plugin_data_dir.rglob('*.png')))

    async def test_image_id_and_owner_boundary(self):
        from astr_auto_anima_hub.auth import require_reader, AuthPrincipal
        job = self.job(self.image('image'))
        self.app.dependency_overrides[require_reader] = lambda: AuthPrincipal(role='user', subject='other')
        result = await self.call('GET', f'/api/v1/lite/jobs/{job.id}/images/image/prompt')
        self.assertEqual(result.status_code, 404)

    async def test_new_compiled_prompt_overrides_old_source_and_does_not_repeat_addition(self):
        image = self.image('image', prompt='old source', addition='rain')
        image.final_prompt = 'edited character, rain, watercolor'
        job = self.job(image)
        saved = await self.favorite(job, 'image')
        self.assertEqual(saved.status_code, 200, saved.text)
        rows = list_favorites(self.settings.prompt_favorites_path, self.principal)
        self.assertEqual(rows.items[0].prompt, image.final_prompt)

    async def test_legacy_is_explicitly_not_actual(self):
        job = self.job(self.image('image'))
        result = await self.call('GET', f'/api/v1/lite/jobs/{job.id}/images/image/prompt')
        self.assertEqual(result.json()['kind'], 'legacy_source')
