import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import first_run_checks as checks
from first_run_config import SetupError, SetupSession, validate_api_key, validate_dictionary


class ChecksTests(unittest.TestCase):
    def test_prefix_and_wrong_tokens_rejected(self):
        for key in ['abk_' + 'x' * 8, 'Bearer abk_' + 'x' * 43, 'admin-' + 'x' * 48, 'abk_...']:
            with self.subTest(key=key), self.assertRaises(SetupError): validate_api_key(key)
        self.assertEqual(validate_api_key(''), '')
        with self.assertRaises(SetupError): validate_api_key('', True)
        self.assertEqual(len(validate_api_key('abk_' + 'x' * 43)), 47)

    def test_dictionary_invalid_duplicate(self):
        for data in [{'prompts': []}, {'characters': []}, {'characters': [{'tag': 'a'}, {'tag': 'a'}]},
                     {'characters': [{'tag': 'a', 'aliases': 'bad'}]}]:
            with self.assertRaises(SetupError): validate_dictionary(data)
        self.assertEqual(validate_dictionary({'characters': [{'tag': 'a', 'aliases': ['示例']}]}), 1)

    def test_dictionary_stage_backup_and_no_edits_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d).resolve(); data = base / 'data'; data.mkdir()
            runtime = base / 'runtime-env.json'; runtime.write_text(json.dumps({'AAH_PLUGIN_DATA_DIR': str(data)}))
            path = data / 'character_dictionary.json'; path.write_text(json.dumps({'characters': [{'tag': 'old'}]}))
            edits = data / 'character_dictionary_edits.json'; edits.write_text('keep')
            session = SetupSession(runtime)
            session.stage_dictionary({'characters': [{'tag': 'new'}]})
            self.assertEqual(json.loads(path.read_text())['characters'][0]['tag'], 'old')
            backups = session.commit()
            self.assertEqual(len(backups), 1)
            self.assertEqual(edits.read_text(), 'keep')
            self.assertEqual(json.loads(path.read_text())['characters'][0]['tag'], 'new')

    def test_workflow_missing_node_and_model(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'flow.json'
            p.write_text(json.dumps({'1': {'class_type': 'Loader', 'inputs': {'model': 'missing'}}, '2': {'class_type': 'Absent'}}))
            with patch.object(checks, 'request_json', side_effect=[{'Loader': {'input': {'required': {'model': [['present']]}}}}, {'devices': []}]):
                text = checks.check_workflow('http://localhost:8188', p)
            self.assertIn('missing', text); self.assertIn('Absent', text); self.assertIn('未报告 CUDA', text)

    def test_submission_default_does_not_send_im(self):
        with patch.object(checks, 'request_json', return_value={'id': 'a' * 32}) as req:
            checks.submit_test('http://localhost:6278', 'demo', 'test')
            payload = req.call_args.kwargs['payload']
            self.assertFalse(payload['deliver_to_im']); self.assertFalse(payload['five_draw'])
            self.assertEqual(payload['kind'], 'direct')
            self.assertEqual(payload['safety_code'], 'N')

    def test_image_hash_and_url_not_trusted(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN6sAAAAASUVORK5CYII=')
        job = {'id': 'a' * 32, 'status': 'succeeded', 'images': [{'id': 'img1', 'size_bytes': len(png),
               'sha256': hashlib.sha256(png).hexdigest(), 'download_url': 'https://attacker.invalid'}]}
        with patch.object(checks, 'request_bytes', return_value=png) as req:
            result = checks.fetch_image('http://localhost:6278', 'private', job)
            self.assertTrue(result[2]); self.assertNotIn('attacker', str(req.call_args))
        job['images'][0]['sha256'] = '0' * 64
        with patch.object(checks, 'request_bytes', return_value=png), self.assertRaises(SetupError):
            checks.fetch_image('http://localhost:6278', 'private', job)
        with self.assertRaises(SetupError): checks.fetch_image('http://localhost:6278', '', {'status': 'succeeded', 'images': []})

    def test_no_cleartext_remote_key(self):
        with patch('urllib.request.build_opener') as opener, self.assertRaises(SetupError):
            checks.request_json('http://192.0.2.1:6185', '/api/v1/chat/sessions', 'secret')
        opener.assert_not_called()

    def test_existing_builder_shared_format(self):
        source = Path(__file__).resolve().parents[2] / 'plugin/astrbot_plugin_comfy_bridge/tools'
        if source.exists(): sys.path.insert(0, str(source))
        from build_character_dictionary import build_dictionary
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'characters.jsonl'
            path.write_text(json.dumps({'id': 1, 'name': 'example', 'aliases': ['test'], 'post_count': 5}) + '\n')
            data = build_dictionary(path)
            self.assertEqual(validate_dictionary(data), 1)
            self.assertNotIn(d, json.dumps(data))

    def test_real_http_mock_full_chain_and_auth_failures(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN6sAAAAASUVORK5CYII=')
        job = {'id': 'b' * 32, 'status': 'succeeded', 'images': [{'id': 'image', 'size_bytes': len(png), 'sha256': hashlib.sha256(png).hexdigest()}]}
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                requests.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302); self.send_header('Location', '/leaked'); self.end_headers(); return
                if self.path == '/denied':
                    self.send_response(401); self.end_headers(); self.wfile.write(b'secret reflected'); return
                self.send_response(200); self.end_headers()
                body = png if '/images/' in self.path else json.dumps({'targets': [{'id': 'test', 'label': 'Test'}]} if self.path.endswith('delivery-targets') else job).encode()
                self.wfile.write(body)
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                self.send_response(202); self.end_headers(); self.wfile.write(json.dumps(job).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            self.assertIn('通过', checks.check_astrbot(url, 'abk_' + 'x' * 43))
            self.assertEqual(checks.targets(url, 'test')[0]['id'], 'test')
            created = checks.submit_test(url, 'test', 'test')
            final = checks.job_status(url, 'test', created['id'])
            self.assertEqual(checks.fetch_image(url, 'test', final)[0], png)
            with self.assertRaises(SetupError) as error: checks.request_json(url, '/denied', 'secret')
            self.assertNotIn('secret', str(error.exception))
            with self.assertRaises(SetupError): checks.request_json(url, '/redirect', 'secret')
            self.assertNotIn('/leaked', requests)
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__': unittest.main()
