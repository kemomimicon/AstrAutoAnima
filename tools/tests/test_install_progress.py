"""Progress follows real work: failures never become success or fake percentages."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_progress import StageProgress, ProgressLog, ProgressModel, ProgressPanel, stream_command
from deploy_project import DeploymentProgress, DISPLAY_STEPS
from easy_installer import sha256_file, download_file
from download_network import DownloadNetwork, fetch_public_file


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.events, self.logs = [], []
        self.log = ProgressLog(self.logs.append, self.events.append)

    def test_journal_events_skips_and_final_stage_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DeploymentProgress(Path(tmp), self.log)
            model = ProgressModel(DISPLAY_STEPS)
            for key, _ in DISPLAY_STEPS:
                tracker.stage(key)
                if key in {'dependencies', 'optional'}: tracker.skip('未勾选')
            tracker.finish('completed')
            for event in self.events: model.update(event)
            state = json.loads((Path(tmp) / 'deployment-status.json').read_text('utf-8'))
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['states']['services'], 'done')
        self.assertEqual(state['states']['optional'], 'skipped')
        self.assertEqual(model.completed, 9)
        self.assertEqual(len(state['completed']), 9)
        self.assertEqual(len(state['completed']), len(set(state['completed'])))

    def test_failure_is_current_stage_and_does_not_complete_rest(self):
        tracker = StageProgress(DISPLAY_STEPS, self.log)
        tracker.stage('prepare'); tracker.stage('environments'); tracker.finish('failed')
        model = ProgressModel(DISPLAY_STEPS)
        for event in self.events: model.update(event)
        self.assertEqual(model.status, 'failed')
        self.assertEqual(model.states['environments'], 'failed')
        self.assertEqual(model.states['project'], 'waiting')
        self.assertEqual(model.completed, 1)

    def test_unready_service_is_amber_not_failed_install(self):
        tracker = StageProgress((('services', '检查服务'),), self.log)
        tracker.stage('services'); tracker.attention('尚未就绪'); tracker.finish('needs_attention')
        model = ProgressModel((('services', '检查服务'),))
        for event in self.events: model.update(event)
        self.assertEqual(model.status, 'needs_attention')
        self.assertEqual(model.states['services'], 'attention')
        self.assertEqual(model.completed, 1)

    def test_download_100_percent_is_not_install_complete(self):
        model = ProgressModel(DISPLAY_STEPS)
        model.update({'kind': 'stages', 'stage': 'models', 'status': 'running', 'states': {'models': 'running'}})
        model.update({'kind': 'transfer', 'name': 'model', 'current': 100, 'total': 100})
        self.assertEqual(model.file_percent, 100)
        self.assertEqual(model.completed, 0)
        self.assertEqual(model.status, 'running')
        model.update({'kind': 'activity', 'name': 'pip', 'current': None, 'total': None})
        self.assertIsNone(model.file_percent)

    def test_stage_change_and_retry_clear_old_transfer_and_failure(self):
        model = ProgressModel(DISPLAY_STEPS)
        model.update({'kind': 'transfer', 'current': 40, 'total': 100})
        model.update({'kind': 'stages', 'stage': 'configuration', 'status': 'running', 'states': {'configuration': 'running'}})
        self.assertIsNone(model.file_percent)
        model.finish('failed', 'fixture failure'); model.reset(DISPLAY_STEPS)
        self.assertEqual(model.status, 'idle')
        self.assertTrue(all(v == 'waiting' for v in model.states.values()))

    def test_quiet_real_subprocess_has_heartbeat_and_returns(self):
        stream_command([sys.executable, '-c', 'import time; time.sleep(.25)'], self.log, heartbeat=.05)
        self.assertTrue(any('仍在运行' in s for s in self.logs))
        self.assertEqual(self.events[0]['kind'], 'activity')

    def test_real_subprocess_output_and_nonzero_exit_reported(self):
        with self.assertRaisesRegex(RuntimeError, '退出码 7'):
            stream_command([sys.executable, '-c', 'print("visible output", flush=True); raise SystemExit(7)'], self.log)
        self.assertIn('visible output', self.logs)

    def test_hash_progress_reports_real_size_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.bin'; data = b'not-a-model' * 1024
            path.write_bytes(data)
            self.assertEqual(sha256_file(path, self.log), hashlib.sha256(data).hexdigest())
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.events[-1]['current'], len(data))
        self.assertEqual(self.events[-1]['total'], len(data))

    def test_resumed_download_progress_uses_expected_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'fixture.bin'
            part = target.with_name(target.name + '.part'); part.write_bytes(b'ab')
            def fetch(curl, url, partial, log, network): partial.write_bytes(b'abcd')
            with patch('easy_installer.shutil.which', return_value='curl'), patch('download_network.fetch_public_file', side_effect=fetch):
                download_file('https://example.invalid/file', target, self.log, expected_size=4,
                              expected_sha256=hashlib.sha256(b'abcd').hexdigest())
            self.assertEqual(target.read_bytes(), b'abcd')
        event = next(e for e in self.events if e['kind'] == 'transfer')
        self.assertEqual((event['current'], event['total']), (2, 4))

    def test_curl_ticks_report_bytes_without_output_scraping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.part'; path.write_bytes(b'123')
            process = MagicMock(); process.__enter__.return_value = process
            process.returncode = 0
            process.communicate.side_effect = [subprocess.TimeoutExpired('curl', 1), (b'AAA_HTTP:200', None)]
            with patch('download_network.subprocess.Popen', return_value=process):
                fetch_public_file('curl', 'https://example.invalid/file', path, self.log, DownloadNetwork())
        self.assertTrue(any(e.get('current') == 3 for e in self.events))
        self.assertTrue(all(c.kwargs.get('timeout') == 1 for c in process.communicate.call_args_list))

    @unittest.skipUnless(os.name == 'nt' or os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY'), 'Tk UI requires a desktop')
    def test_tk_lights_unknown_length_download_failure_and_reset(self):
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        try:
            panel = ProgressPanel(root, DISPLAY_STEPS); panel.frame.pack(fill='x')
            panel.update({'kind': 'stages', 'stage': 'models', 'status': 'running', 'states': {'models': 'running'}})
            self.assertTrue(panel.animating)
            panel.update({'kind': 'transfer', 'current': 50, 'total': 100})
            self.assertFalse(panel.animating)
            self.assertEqual(float(panel.activity['value']), 50)
            panel.finish('failed', '测试失败')
            self.assertIn('失败', panel.light_widgets['models'][2].cget('text'))
            self.assertEqual(panel.light_widgets['models'][0].itemcget(panel.light_widgets['models'][1], 'fill'), '#c63232')
            panel.reset(DISPLAY_STEPS)
            self.assertIn('待执行', panel.light_widgets['models'][2].cget('text'))
            root.update_idletasks()
        finally:
            root.destroy()


if __name__ == '__main__': unittest.main()
