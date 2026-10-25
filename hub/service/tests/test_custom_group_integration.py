import asyncio
import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from pydantic import ValidationError
from astr_auto_anima_hub.auth import SYSTEM_ADMIN
from astr_auto_anima_hub.prompt_groups import groups_path
from astr_auto_anima_hub.remote_jobs import RemoteJobManager, RemoteJobError, build_remote_command, load_delivery_targets
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest


class CustomGroupIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            from .test_api import ApiTests
        except ImportError:
            from test_api import ApiTests
        self.fixture = ApiTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.settings = self.fixture.settings
        self.client = self.fixture.client
        targets_path = self.settings.delivery_targets_override
        targets = json.loads(targets_path.read_text(encoding='utf-8'))
        targets['targets'].append({'id': 'private-test', 'label': 'Private test',
                                  'kind': 'private', 'umo': 'examplebot:FriendMessage:654321',
                                  'allow_safety': ['N', 'H', 'S']})
        targets_path.write_text(json.dumps(targets), encoding='utf-8')
        path = groups_path(self.settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'groups': [
            {'id': 'night_scene', 'name': '夜景', 'allow_private': False},
            {'id': 'rain', 'name': '雨天', 'allow_private': True},
        ]}), encoding='utf-8')
        self.settings.prompt_pool_path.write_text(json.dumps({'prompts': [
            {'id': 'a', 'prompt': 'night rain', 'custom_groups': ['night_scene', 'rain'], 'source_code': 'D', 'safety_code': 'N'},
            {'id': 'b', 'prompt': 'dry night', 'custom_groups': ['night_scene'], 'source_code': 'D', 'safety_code': 'N'},
            {'id': 'c', 'prompt': 'day', 'custom_groups': [], 'source_code': 'D', 'safety_code': 'N'},
        ]}), encoding='utf-8')

    def test_reader_registry_and_filtered_pages_use_intersection(self):
        endpoint = '/api/v1/lite/prompt-groups'
        self.assertIn(self.client.get(endpoint).status_code, (401, 403))
        registry = self.client.get(endpoint, headers=self.fixture.user_headers)
        self.assertEqual(registry.status_code, 200)
        self.assertEqual([g['id'] for g in registry.json()['groups']], ['night_scene', 'rain'])
        for endpoint, headers in (('/api/v1/lite/prompts', self.fixture.user_headers),
                                  ('/api/v1/prompts', self.fixture.headers)):
            result = self.client.get(endpoint, params={'custom_groups': 'night_scene,rain'}, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([p['id'] for p in result.json()['items']], ['a'])
            bad = self.client.get(endpoint, params={'custom_groups': 'removed'}, headers=headers)
            self.assertEqual(bad.status_code, 422)
        favorite = self.client.get('/api/v1/lite/prompts', params={'source': 'P', 'custom_groups': 'rain'},
                                   headers=self.fixture.user_headers)
        self.assertEqual(favorite.status_code, 422)
        exported = self.client.get('/api/v1/prompts/export',
                                   params={'custom_groups': 'night_scene,rain'},
                                   headers=self.fixture.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual([p['id'] for p in exported.json()['prompts']], ['a'])
        self.assertEqual(exported.json()['filters']['custom_groups'], ['night_scene', 'rain'])
        self.assertEqual(self.client.get('/api/v1/prompts/export',
                         params={'custom_groups': 'deleted'}, headers=self.fixture.headers).status_code, 422)

    def test_group_command_roundtrips_through_actual_plugin_selector(self):
        from astrbot_plugin_comfy_bridge.prompt_pool_runtime import parse_group_selector
        target = load_delivery_targets(self.settings.delivery_targets_override)[0]
        request = RemoteJobCreateRequest(target_id=target.public.id, kind='random',
                                         pool_filter='D/N', custom_groups=['NIGHT_scene', 'rain'],
                                         character='someone', random_subject_tag='1boy')
        command, safety = build_remote_command(request, target)
        self.assertIn('D/N @night_scene+rain 起手=1boy', command)
        remaining, selector = parse_group_selector(command.split(' ', 1)[1])
        self.assertEqual(selector['custom_groups'], ['night_scene', 'rain'])
        self.assertEqual(selector['safety_codes'], ['N'])
        self.assertIn('起手=1boy', remaining)
        self.assertEqual(safety, 'N')

    def test_rejects_invalid_identifiers_and_nonrandom_or_k(self):
        for group in ('../x', 'x 角色=someone', '@x', '', 'x/y'):
            with self.subTest(group=group), self.assertRaises(ValidationError):
                RemoteJobCreateRequest(target_id='x', kind='random', custom_groups=[group])
        target = load_delivery_targets(self.settings.delivery_targets_override)[0]
        for kind, pool in (('direct', ''), ('random', 'K/N')):
            with self.assertRaises(RemoteJobError):
                build_remote_command(RemoteJobCreateRequest(target_id=target.public.id, kind=kind,
                                     pool_filter=pool, custom_groups=['rain']), target)

    def test_create_applies_private_policy_before_scheduling(self):
        async def run():
            settings = replace(self.settings, astrbot_api_key='test-only-key')
            manager = RemoteJobManager(settings)
            manager._run = AsyncMock()
            targets = load_delivery_targets(settings.delivery_targets_override)
            private = next(target for target in targets if target.public.kind == 'private')
            group = next(target for target in targets if target.public.kind == 'group')
            for ident in ('night_scene', 'unknown'):
                with self.assertRaises(RemoteJobError):
                    manager.create(RemoteJobCreateRequest(target_id=private.public.id, kind='random',
                                   custom_groups=[ident]), SYSTEM_ADMIN)
                manager._run.assert_not_called()
                self.assertEqual(manager._jobs, {})
            job = manager.create(RemoteJobCreateRequest(target_id=group.public.id, kind='random',
                                 custom_groups=['night_scene']), SYSTEM_ADMIN)
            await asyncio.gather(*tuple(manager._tasks))
            self.assertIn('@night_scene', job.command_preview)
            manager._run.assert_awaited_once()
        asyncio.run(run())
