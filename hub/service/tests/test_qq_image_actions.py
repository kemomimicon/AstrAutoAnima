import hashlib
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import test_kp_lora_personal as fixtures
from astr_auto_anima_hub.qq_image_actions import handle_qq_action
from astr_auto_anima_hub.prompt_reports import PromptReports
from astr_auto_anima_hub.repositories import RepositoryError, list_prompts
from astr_auto_anima_hub.auth import AuthPrincipal


class QQImageActionTests(unittest.TestCase):
    setUp = fixtures.KpLoraPersonalTests.setUp
    tearDown = fixtures.KpLoraPersonalTests.tearDown

    def prepare(self):
        root = self.settings.plugin_data_dir
        self.settings.lite_users_path.write_text(json.dumps({'users': [
            {'id': 'qq-user', 'label': 'user', 'qq': '123456', 'token_sha256': 'a'*64}]}))
        for name in ['jobs', 'assets']:
            (root / 'job_store' / name).mkdir(parents=True, exist_ok=True)
        image = root / 'test.png'
        image.write_bytes(b'original-output')
        (root / 'job_store' / 'jobs' / 'job_test.json').write_text(json.dumps({
            'result': {'assets': ['img_other', 'img_test']},
            'input': {'source_entries': [{'id': 'wrong', 'prompt': 'wrong'}, {'id': 'good-001', 'prompt': 'actual snapshot'}]}}))
        (root / 'job_store' / 'assets' / 'img_test.json').write_text(json.dumps({
            'job_id': 'job_test', 'asset_id': 'img_test', 'type': 'result', 'path': str(image),
            'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}))
        self.jobs = SimpleNamespace(unmark_liked=Mock(), _require_approved=lambda content: None)
        self.reports = PromptReports(self.settings, self.jobs)
        return image

    def call(self, action, qq='123456', **changes):
        token = uuid.uuid4().hex
        root = self.settings.hub_state_dir / 'qq_image_actions'
        root.mkdir(exist_ok=True)
        (root / (token + '.json')).write_text(json.dumps({
            'action': action, 'qq': qq, 'job_id': 'job_test', 'asset_id': 'img_test',
            'expires_at': time.time() + 60, 'reason': 'bad composition', **changes}))
        self.last_token = token
        return handle_qq_action(self.settings, self.reports, self.jobs, token)

    def test_favorite_shares_personal_client_identity_and_is_idempotent(self):
        self.prepare()
        self.assertIn('已收藏', self.call('favorite')['message'])
        self.assertIn('已经收藏', self.call('favorite')['message'])
        self.assertEqual(list_prompts(self.settings.prompt_pool_path, source='P', owner='qq-user').total, 1)
        self.assertEqual(list_prompts(self.settings.prompt_pool_path, source='P', owner='someone-else').total, 0)
        self.call('unfavorite')
        self.assertEqual(list_prompts(self.settings.prompt_pool_path, source='P', owner='qq-user').total, 0)
        self.assertEqual(list_prompts(self.settings.prompt_pool_path, source='B').total, 1)
        self.jobs.unmark_liked.assert_called_once()

    def test_report_snapshot_evidence_dedup_and_admin_review(self):
        image = self.prepare()
        self.call('report', qq='654321')  # Reports also work for unregistered QQ.
        self.assertIn('已经举报', self.call('report', qq='654321')['message'])
        rows = self.reports.list()['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['prompt_id'], 'good-001')
        self.assertEqual(rows[0]['snapshot']['prompt']['prompt'], 'actual snapshot')
        self.assertEqual(rows[0]['snapshot']['qq'], '654321')
        image.write_bytes(b'replaced')
        self.assertEqual(self.reports.image(rows[0]['id'])[0].read_bytes(), b'original-output')
        self.assertEqual(list_prompts(self.settings.prompt_pool_path, source='B').total, 1)
        self.reports.resolve(rows[0]['id'], 'trash', AuthPrincipal(role='admin', subject='administrator'))
        self.assertFalse(json.loads(self.settings.prompt_pool_path.read_text())['prompts'][0]['enabled'])

    def test_unknown_user_expiry_bad_asset_and_replay_rejected(self):
        self.prepare()
        for values in [dict(qq='987654'), dict(expires_at=0), dict(asset_id='../escape')]:
            with self.subTest(values=values), self.assertRaises(RepositoryError):
                self.call('favorite', **values)
        self.call('favorite')
        with self.assertRaises(RepositoryError):
            handle_qq_action(self.settings, self.reports, self.jobs, self.last_token)

    def test_no_prompt_can_report_but_not_favorite_or_trash(self):
        self.prepare()
        path = self.settings.plugin_data_dir / 'job_store' / 'jobs' / 'job_test.json'
        data = json.loads(path.read_text())
        data['input']['source_entries'] = []
        path.write_text(json.dumps(data))
        with self.assertRaises(RepositoryError):
            self.call('favorite')
        self.call('report')
        row = self.reports.list()['items'][0]
        with self.assertRaises(RepositoryError):
            self.reports.resolve(row['id'], 'trash', AuthPrincipal(role='admin', subject='administrator'))
