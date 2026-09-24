import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from first_run_config import SetupError, SetupSession, probe_health, safe_path, target_record, validate_url


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aaa-first-run-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / 'plugin_data'; self.data.mkdir()
        self.runtime = self.root / 'runtime-env.json'
        self.env = {'AAH_PLUGIN_DATA_DIR': str(self.data), 'AAH_ADMIN_TOKEN': 'test-' + 'a' * 48,
                    'AAH_ASTRBOT_URL': 'http://127.0.0.1:6185', 'AAH_COMFYUI_URL': 'http://127.0.0.1:8188',
                    'AAH_ASTRBOT_BOT_ID': 'demo-bot', 'AAH_ASTRBOT_API_KEY': '', 'MY_CUSTOM_SETTING': 'preserve'}
        self.write(self.runtime, self.env)

    def write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def test_load_and_cancel_has_no_writes(self):
        before = self.runtime.read_bytes()
        session = SetupSession(self.runtime)
        session.add_user('123456789', 'test')
        session.add_target(target_record('group1', 'test', 'demo-bot', '123456789', 'group'))
        self.assertEqual(self.runtime.read_bytes(), before)
        self.assertEqual(list(self.data.iterdir()), [])

    def test_commit_preserves_settings_and_creates_backup(self):
        old = self.runtime.read_bytes()
        session = SetupSession(self.runtime)
        session.set_connections({'AAH_ASTRBOT_BOT_ID': 'updated-bot'})
        backups = session.commit()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        result = json.loads(self.runtime.read_text())
        self.assertEqual(result['MY_CUSTOM_SETTING'], 'preserve')
        self.assertEqual(result['AAH_ADMIN_TOKEN'], self.env['AAH_ADMIN_TOKEN'])
        self.assertEqual(session.commit(), [])

    def test_concurrent_edit_rejected_before_any_write(self):
        session = SetupSession(self.runtime)
        session.add_user('123456789', 'test')
        self.write(self.runtime, {**self.env, 'OTHER_CHANGE': 'yes'})
        with self.assertRaises(SetupError): session.commit()
        self.assertFalse(session.paths['用户注册表'].exists())

    def test_add_user_hash_only_and_default_no_group(self):
        session = SetupSession(self.runtime)
        session.add_user('123456789', 'test')
        token = session.pending_tokens['123456789']
        session.commit()
        text = session.paths['用户注册表'].read_text()
        self.assertNotIn(token, text)
        row = json.loads(text)['users'][0]
        self.assertEqual(row['token_sha256'], hashlib.sha256(token.encode()).hexdigest())
        self.assertFalse(row['allow_group'])

    def test_duplicate_user_never_rotates(self):
        session = SetupSession(self.runtime)
        session.add_user('123456789', 'first')
        old = copy.deepcopy(session.users)
        with self.assertRaises(SetupError): session.add_user('123456789', 'second')
        self.assertEqual(session.users, old)

    def test_target_default_and_duplicate_protection(self):
        session = SetupSession(self.runtime)
        row = target_record('demo', 'test', 'demo-bot', '123456789', 'group')
        self.assertEqual(row['allow_safety'], ['N'])
        session.add_target(row)
        with self.assertRaises(SetupError): session.add_target(row)
        self.assertEqual(len(session.targets['targets']), 1)

    def test_invalid_target_rejected(self):
        for args in [('self-private', 'test', 'bot', '123456789', 'private'),
                     ('group', '', 'bot', '123456789', 'group'),
                     ('group', 'test', 'bad:bot', '123456789', 'group'),
                     ('group', 'test', 'bot', 'not-number', 'group')]:
            with self.subTest(args=args), self.assertRaises(SetupError): target_record(*args)

    def test_import_preserves_custom_groups_and_skips_duplicate_ids(self):
        session = SetupSession(self.runtime)
        source = self.root / 'incoming.json'
        self.write(source, {'prompts': [{'id': 'demo-1', 'prompt': 'park', 'custom_groups': ['rain']}],
                            'custom_group_definitions': [{'id': 'rain', 'name': 'Rain'}]})
        self.assertEqual(session.import_pool(source), (1, 0))
        self.assertEqual(session.import_pool(source), (0, 0))
        self.assertEqual(session.pool['custom_group_definitions'][0]['id'], 'rain')
        session.commit()
        result = json.loads(session.paths['提示词库'].read_text())
        self.assertEqual(result['prompts'][0]['custom_groups'], ['rain'])

    def test_import_invalid_does_not_change_staged_pool(self):
        session = SetupSession(self.runtime)
        source = self.root / 'bad.json'; self.write(source, {'prompts': [{'id': 'bad', 'prompt': ''}]})
        before = copy.deepcopy(session.pool)
        with self.assertRaises(ValueError): session.import_pool(source)
        self.assertEqual(session.pool, before)

    def test_summary_hides_secrets(self):
        session = SetupSession(self.runtime)
        secret = 'abk_' + 'z' * 43
        session.set_connections({'AAH_ASTRBOT_API_KEY': secret})
        self.assertNotIn(secret, session.summary())
        self.assertNotIn(self.env['AAH_ADMIN_TOKEN'], session.summary())

    def test_invalid_connections_not_staged(self):
        session = SetupSession(self.runtime)
        for values in [{'AAH_ADMIN_TOKEN': 'short'}, {'AAH_ASTRBOT_BOT_ID': 'your-bot-id'},
                       {'AAH_ASTRBOT_URL': 'http://user:password@example.com'}, {'UNSUPPORTED': 'x'}]:
            with self.subTest(values=values), self.assertRaises(SetupError): session.set_connections(values)
        self.assertEqual(session.changes(), [])

    def test_missing_and_wrong_runtime(self):
        with self.assertRaises(SetupError): SetupSession(self.root / 'missing.json')
        with self.assertRaises(SetupError): SetupSession(self.root / 'missing/runtime-env.json')

    def test_missing_data_dir_is_not_created(self):
        self.write(self.runtime, {**self.env, 'AAH_PLUGIN_DATA_DIR': str(self.root / 'missing')})
        with self.assertRaises(SetupError): SetupSession(self.runtime)
        self.assertFalse((self.root / 'missing').exists())

    def test_overlapping_files_rejected(self):
        self.write(self.runtime, {**self.env, 'AAH_LITE_USERS_PATH': str(self.runtime)})
        with self.assertRaises(SetupError): SetupSession(self.runtime)

    def test_relative_and_foreign_paths_rejected(self):
        for value in ('relative.json', '"bad-path"', '/srv/config.json' if os.name == 'nt' else 'C:/config.json'):
            with self.subTest(value=value), self.assertRaises(SetupError): safe_path(value)

    def test_url_validation(self):
        self.assertEqual(validate_url('http://127.0.0.1:6278/'), 'http://127.0.0.1:6278')
        for value in ('file:///tmp/a', 'https://x/api/v1/health', 'https://x/?token=secret', 'https://x:bad'):
            with self.subTest(value=value), self.assertRaises(SetupError): validate_url(value)

    def test_probe_does_not_echo_error_or_secrets(self):
        with patch('urllib.request.build_opener', side_effect=RuntimeError('secret should not show')):
            self.assertNotIn('secret', probe_health('http://127.0.0.1:6278'))

    def test_partial_failure_reports_saved_files(self):
        session = SetupSession(self.runtime)
        session.set_connections({'AAH_ASTRBOT_BOT_ID': 'updated-bot'})
        session.add_user('123456789', 'test')
        original_replace = os.replace
        def replace(source, target):
            if Path(target) == session.paths['用户注册表']: raise OSError('simulated failure')
            return original_replace(source, target)
        with patch('first_run_config.os.replace', side_effect=replace):
            with self.assertRaisesRegex(SetupError, '已保存：服务连接'): session.commit()
        self.assertEqual(json.loads(self.runtime.read_text())['AAH_ASTRBOT_BOT_ID'], 'updated-bot')
        self.assertFalse(session.paths['用户注册表'].exists())


if __name__ == '__main__': unittest.main()
