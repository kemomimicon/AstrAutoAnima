from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import os
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import online_prompt_importer as importer


class OnlineImporterTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows native CMD transport')
    def test_native_drag_launcher_preserves_unicode_spaces_and_shell_characters(self):
        with tempfile.TemporaryDirectory(prefix='aaa-drag-') as tmp:
            root = Path(tmp)
            source = Path(__file__).resolve().parents[1] / 'Import-Prompt-Files.cmd'
            launcher = root / 'Import Files.cmd'
            launcher.write_bytes(source.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            capture = root / 'capture.json'
            stub = root / 'capture.py'
            stub.write_text('import json,os,pathlib\npathlib.Path(os.environ["AAA_IMPORT_CAPTURE"]).write_text(json.dumps([os.environ[f"AAA_IMPORT_FILE_{i}"] for i in range(1,int(os.environ["AAA_IMPORT_COUNT"])+1)]),encoding="utf-8")\n', encoding='utf-8')
            (root / 'py.cmd').write_text(f'@echo off\r\n"{sys.executable}" "{stub}"\r\n', encoding='ascii')
            paths = [root / '中文 空格 & !.json', root / '100% (old).txt']
            for p in paths: p.write_text('garden', encoding='utf-8')
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'AAA_IMPORT_CAPTURE': str(capture)}
            command = '"' + ' '.join('"' + str(p) + '"' for p in [launcher, *paths]) + '"'
            run = subprocess.run('cmd.exe /d /s /c ' + command, env=env,
                                 capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(json.loads(capture.read_text('utf-8')), [str(p) for p in paths])

    def test_multiple_legacy_exports_encodings_and_cross_file_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / '旧库.json', root / '中文.csv', root / 'extra.txt']
            paths[0].write_text(json.dumps({'prompts': [
                {'id': 'old', 'prompt': 'Blue sky', 'safety_level': 'normal'},
                {'prompt': 'mountain'}]}), encoding='utf-8-sig')
            paths[1].write_bytes('提示词\nblue SKY\n山水\n'.encode('gb18030'))
            paths[2].write_text('mountain\nforest\n', encoding='utf-8')
            before = [p.read_bytes() for p in paths]
            prompts, report = importer.parse_files(paths)
            self.assertEqual(prompts, ['Blue sky', 'mountain', '山水', 'forest'])
            self.assertEqual([r['duplicates_in_batch'] for r in report], [0, 1, 1])
            self.assertEqual([p.read_bytes() for p in paths], before)

    def test_batch_preflight_rejects_bad_file_without_network_or_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(importer, 'request') as request:
            good, bad = Path(tmp) / 'good.txt', Path(tmp) / 'broken.json'
            good.write_text('garden', encoding='utf-8')
            bad.write_text('{bad', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'broken.json'):
                importer.parse_files([good, bad])
            with self.assertRaises(ValueError): importer.parse_files([])
            with self.assertRaises(ValueError): importer.parse_files([good] * 65)
            request.assert_not_called()

    def test_batch_selection_above_old_single_file_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'large.txt'
            p.write_text('\n'.join('landscape ' + str(i) for i in range(10001)), encoding='utf-8')
            prompts, files = importer.parse_files([p])
            self.assertEqual(len(prompts), 10001)
            self.assertEqual(files[0]['added_to_batch'], 10001)

    def test_dropped_paths_are_data_not_commands(self):
        paths = [r'D:\中文 空格\a & b!.json', r'D:\模型\100% (test).txt']
        env = {'AAA_IMPORT_COUNT': '2', **{f'AAA_IMPORT_FILE_{i}': p for i, p in enumerate(paths, 1)}}
        self.assertEqual(importer.dropped_files(env), paths)
        for count in ('bad', '-1', '65'):
            with self.assertRaises(ValueError): importer.dropped_files({'AAA_IMPORT_COUNT': count})
        with self.assertRaises(ValueError): importer.dropped_files({'AAA_IMPORT_COUNT': '1'})

    def args(self): return ('http://127.0.0.1:6278', 'fixture-token', 'example', '示例', False, 'B', 'N', ['a normal landscape'])

    def test_parse_json_csv_txt_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in [('a.json', '{"items":[" Blue sky ",{"prompt":"blue SKY"},"mountain"]}'),
                               ('a.csv', '提示词\n"Blue sky"\n"mountain"\n'), ('a.txt', '# comment\nBlue sky\nblue SKY\nmountain')]:
                path = Path(tmp) / name; path.write_text(data, 'utf-8')
                result = importer.parse_file(path)
                self.assertEqual(len(result), 2)
            bad = Path(tmp) / 'bad.json'; bad.write_text('[{"prompt":{"url":"not-text"}}]', 'utf-8')
            with self.assertRaises(ValueError): importer.parse_file(bad)

    def test_file_count_and_text_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'many.txt'; path.write_text('\n'.join(str(i) for i in range(10001)), 'utf-8')
            with self.assertRaises(ValueError): importer.parse_file(path)
            path.write_text('a' * 20001, 'utf-8')
            with self.assertRaises(ValueError): importer.parse_file(path)

    def test_consent_and_parameters_before_any_network(self):
        with patch.object(importer, 'request') as request:
            with self.assertRaises(ValueError): importer.sync(*self.args())
            for index, value in [(0,'http://remote.invalid'), (1,''), (1,'中文密钥'), (1,'bad token'), (1,'bad\0token'), (2,'../bad'), (4,'false'), (6,'unknown'), (7,[])]:
                args = list(self.args()); args[index] = value
                with self.assertRaises(ValueError): importer.sync(*args, consent=True)
            request.assert_not_called()

    def test_missing_groups_api_never_writes(self):
        with patch.object(importer, 'request', side_effect=importer.ImportFailure('HTTP 404')) as request:
            with self.assertRaises(importer.ImportFailure): importer.sync(*self.args(), consent=True)
            self.assertEqual([c.args[2] for c in request.call_args_list], ['GET'])

    def test_existing_group_different_permissions_never_overwritten(self):
        registry = {'revision':'r1', 'groups':[{'id':'example', 'name':'示例', 'allow_private':True}]}
        with patch.object(importer, 'request', return_value=registry) as request:
            with self.assertRaisesRegex(ValueError, '不在导入时覆盖'): importer.sync(*self.args(), consent=True)
            self.assertEqual(request.call_count, 1)

    def test_existing_group_no_put_and_import_keeps_text(self):
        registry = {'revision':'r1', 'groups':[{'id':'example', 'name':'示例', 'allow_private':False}]}
        with patch.object(importer, 'request', side_effect=[registry, {'revision':'r2'}, {'count':1}]) as request:
            self.assertEqual(importer.sync(*self.args(), consent=True), (1,0))
            self.assertEqual([c.args[2] for c in request.call_args_list], ['GET','GET','POST'])
            self.assertEqual(request.call_args.args[4]['prompts'][0]['prompt'], 'a normal landscape')
            self.assertEqual(request.call_args.args[5], 'r2')

    def test_current_group_permissions_survive_when_new_import_group_is_added(self):
        row = {'id':'existing', 'name':'原组', 'allow_private':False,
               'allow_group':False, 'enabled':False, 'safety_codes':['H']}
        registry = {'revision':'r1', 'groups':[row]}
        with patch.object(importer, 'request', side_effect=[registry, {}, {'revision':'r2'}, {'count':1}]) as request:
            self.assertEqual(importer.sync(*self.args(), consent=True), (1, 0))
            self.assertEqual(request.call_args_list[1].args[4]['groups'][0], row)

    def test_future_group_fields_never_dropped_by_registry_write(self):
        registry = {'revision':'r1', 'groups':[{'id':'protected', 'name':'Protected', 'allow_private':False, 'future_permission':'keep'}]}
        with patch.object(importer, 'request', return_value=registry) as request:
            with self.assertRaisesRegex(ValueError, '未知字段'): importer.sync(*self.args(), consent=True)
            self.assertEqual(request.call_count, 1)

    def test_batch_failure_reports_partial_does_not_replay(self):
        args = list(self.args()); args[-1] = ['safe landscape ' + str(i) for i in range(501)]
        with patch.object(importer, 'request', side_effect=[{'revision':'a','groups':[]}, {}, {'revision':'b'}, {'count':500}, {'revision':'c'}, importer.ImportFailure('fixture timeout')]) as request:
            with self.assertRaisesRegex(importer.ImportFailure, '已确认 1 批、新增 500 条'): importer.sync(*args, consent=True)
            self.assertEqual([c.args[2] for c in request.call_args_list], ['GET','PUT','GET','POST','GET','POST'])

    def test_redirect_and_system_proxy_not_used_and_errors_redacted(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError('https://fixture.invalid', 302, 'secret-response', {}, None)
        with patch.object(importer.urllib.request, 'build_opener', return_value=opener) as build:
            with self.assertRaises(importer.ImportFailure) as caught:
                importer.request('https://fixture.invalid', 'do-not-echo', 'GET', '/api/v1/prompts/groups')
            self.assertNotIn('do-not-echo', str(caught.exception)); self.assertNotIn('secret-response', str(caught.exception))
            self.assertEqual(build.call_args.args[1].proxies, {})
            self.assertIsNone(build.call_args.args[0].redirect_request(None, None, 302, '', {}, 'https://other.invalid'))
            self.assertEqual(opener.open.call_count, 1)

    def test_unknown_route_or_invalid_revision_stops(self):
        with patch.object(importer.urllib.request, 'build_opener') as build:
            with self.assertRaises(ValueError): importer.request('http://127.0.0.1', 'fixture', 'POST', '/delete')
            with self.assertRaises(ValueError): importer.request('http://127.0.0.1', 'fixture', 'PUT', '/api/v1/prompts/groups', {}, 'bad\nheader')
            build.assert_not_called()

    def test_malformed_token_not_echoed_or_sent(self):
        with patch.object(importer.urllib.request, 'build_opener') as build:
            for token in ['private-secret中文', 'private-secret\r\nheader', 'private-secret\x01']:
                with self.assertRaises(ValueError) as caught:
                    importer.request('http://127.0.0.1', token, 'GET', '/api/v1/prompts/groups')
                self.assertNotIn('private-secret', str(caught.exception))
            build.assert_not_called()

    def test_real_local_http_import_and_conflict_never_replayed(self):
        events = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def handle_request(self):
                size = int(self.headers.get('Content-Length', '0'))
                payload = json.loads(self.rfile.read(size)) if size else None
                events.append((self.command, self.path, self.headers.get('If-Match'), payload))
                if self.headers.get('Authorization') != 'Bearer fixture-token':
                    self.send_response(401); self.end_headers(); return
                if self.command == 'GET' and self.path.endswith('/groups'):
                    body = {'groups':[], 'revision':'g1'}
                elif self.command == 'PUT':
                    body = {'groups':payload['groups'], 'revision':'g2'}
                elif self.command == 'GET': body = {'revision':'p1'}
                else:
                    self.send_response(409); self.end_headers(); return
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())
            do_GET = handle_request
            do_PUT = handle_request
            do_POST = handle_request
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            args = list(self.args()); args[0] = 'http://127.0.0.1:' + str(server.server_port)
            with self.assertRaisesRegex(importer.ImportFailure, 'HTTP 409'):
                importer.sync(*args, consent=True)
            self.assertEqual([e[0] for e in events], ['GET', 'PUT', 'GET', 'POST'])
            self.assertEqual(events[1][2], 'g1'); self.assertEqual(events[3][2], 'p1')
            self.assertEqual(events[3][3]['prompts'][0]['custom_groups'], ['example'])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
