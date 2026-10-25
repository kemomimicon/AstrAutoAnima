from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import online_prompt_importer as importer


class OnlineImporterTests(unittest.TestCase):
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
