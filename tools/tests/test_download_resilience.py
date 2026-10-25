import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easy_installer import download_file, download_lock, InstallError
from download_network import DownloadNetwork, DownloadFailure, fetch_public_file

BODY = b'known good model bytes' * 200
HASH = hashlib.sha256(BODY).hexdigest()
URL = 'https://huggingface.co/test/model/resolve/' + 'a' * 40 + '/model'


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='aaa-download-test-'); self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name) / 'model.bin'
        self.partial = self.target.with_name(self.target.name + '.part')
        self.logs = []

    def download(self, fetch, **kwargs):
        with patch('easy_installer.shutil.which', return_value='curl'), patch('download_network.fetch_public_file', side_effect=fetch) as mocked:
            download_file(URL, self.target, self.logs.append, expected_sha256=HASH, expected_size=len(BODY), **kwargs)
        return mocked

    def test_bad_full_partial_is_preserved_and_restarted(self):
        self.partial.write_bytes(b'x' * len(BODY))
        def fetch(c, u, p, l, n):
            self.assertFalse(p.exists()); p.write_bytes(BODY)
        self.download(fetch)
        self.assertEqual(self.target.read_bytes(), BODY)
        self.assertEqual(len(list(self.target.parent.glob('*.rejected.*'))), 1)

    def test_html_never_promoted_then_good(self):
        counter = []
        def fetch(c, u, p, l, n):
            counter.append(1); p.write_bytes(b'<html>gateway</html>' if len(counter) == 1 else BODY)
        self.download(fetch)
        self.assertEqual(len(counter), 2)
        self.assertEqual(self.target.read_bytes(), BODY)

    def test_short_success_resumes_instead_of_discarding(self):
        self.partial.write_bytes(BODY[:20])
        offsets = []
        def fetch(c, u, p, l, n):
            have = p.stat().st_size; offsets.append(have)
            with p.open('ab') as f:
                f.write(BODY[have:100] if len(offsets) == 1 else BODY[have:])
        self.download(fetch)
        self.assertEqual(offsets, [20, 100])
        self.assertFalse(list(self.target.parent.glob('*.rejected.*')))

    def test_short_no_progress_preserved_not_promoted(self):
        self.partial.write_bytes(BODY[:20])
        with self.assertRaisesRegex(InstallError, '尚未完整'):
            mocked = self.download(lambda *args: None)
        self.assertEqual(self.partial.read_bytes(), BODY[:20])
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.target.parent.glob('*.rejected.*')))

    def test_short_success_retry_budget_bounded(self):
        calls = []
        def fetch(c, u, p, l, n):
            calls.append(1)
            with p.open('ab') as f: f.write(BODY[len(calls)-1:len(calls)])
        with self.assertRaisesRegex(InstallError, '尚未完整'):
            self.download(fetch)
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.partial.read_bytes(), BODY[:4])

    def test_short_success_keeps_hash_guard(self):
        calls = []
        def fetch(c, u, p, l, n):
            calls.append(1)
            p.write_bytes(b'x' * (10 if len(calls) == 1 else len(BODY)))
        with self.assertRaisesRegex(InstallError, 'SHA256'):
            self.download(fetch)
        self.assertFalse(self.target.exists())

    def test_modelscope_routing_and_opt_in(self):
        ms = 'https://modelscope.cn/models/test/model/resolve/' + 'b' * 40 + '/model'
        self.assertEqual(DownloadNetwork().sources(URL, HASH, ms), [URL])
        self.assertEqual(DownloadNetwork('modelscope').sources(URL, HASH, ms), [ms])
        self.assertEqual(DownloadNetwork('modelscope').sources(URL, HASH), [URL])
        self.assertEqual(DownloadNetwork('modelscope', fallback_official=True).sources(URL, HASH, ms), [ms, URL])
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            DownloadNetwork('modelscope').sources(URL, '', ms)
        for invalid in (ms.replace('modelscope.cn', 'evil.invalid'), ms.replace('b'*40, 'master'), ms + '?token=secret'):
            with self.assertRaises(ValueError): DownloadNetwork('modelscope').sources(URL, HASH, invalid)
        urls = []
        def fetch(c, u, p, l, n): urls.append(u); p.write_bytes(BODY)
        self.download(fetch, network=DownloadNetwork('modelscope'), modelscope_url=ms)
        self.assertEqual(urls, [ms])

    def test_quantized_catalog_targets_and_pairing(self):
        root = Path(__file__).resolve().parents[1]
        catalog = {i['id']: i for i in json.loads((root / 'optional_components.json').read_text('utf-8'))['components']}
        q4, q6 = catalog['joycaption_models_q4']['files'], catalog['joycaption_models']['files']
        self.assertIn('Q4_K_M.gguf', q4[0]['target'])
        self.assertEqual(q4[1], q6[1])
        self.assertLess(q4[0]['size'], q6[0]['size'])
        seed4, seed8 = catalog['seedvr2_models_q4']['files'], catalog['seedvr2_models_q8']['files']
        self.assertEqual(seed4[1], seed8[1])
        self.assertTrue(all(f['target'].startswith('models/SEEDVR2/') for f in seed4 + seed8))
        models = json.loads((root / 'model_catalog.json').read_text('utf-8'))['profiles']['anima-base-1.0']['files']
        for file in models:
            self.assertEqual(DownloadNetwork('modelscope').source(file['url'], file['sha256'], file['modelscope_url']), file['modelscope_url'])

    def test_416_fresh_retry(self):
        self.partial.write_bytes(BODY[:10])
        counter = []
        def fetch(c, u, p, l, n):
            counter.append(1)
            if len(counter) == 1: raise DownloadFailure(22, 416, '416')
            self.assertFalse(p.exists()); p.write_bytes(BODY)
        self.download(fetch)
        self.assertEqual(self.target.read_bytes(), BODY)

    def test_network_error_after_full_write_salvaged(self):
        def fetch(c, u, p, l, n):
            p.write_bytes(BODY); raise DownloadFailure(18, 206, 'EOF')
        self.assertEqual(self.download(fetch).call_count, 1)
        self.assertEqual(self.target.read_bytes(), BODY)

    def test_fallback_only_opt_in(self):
        net = DownloadNetwork('mirror', 'https://mirror.invalid', fallback_official=True)
        urls = []
        def fetch(c, u, p, l, n):
            urls.append(u)
            if 'mirror.invalid' in u: raise DownloadFailure(7, 0, 'connect')
            p.write_bytes(BODY)
        self.download(fetch, network=net)
        self.assertEqual(urls, [URL.replace('huggingface.co', 'mirror.invalid'), URL])
        self.assertEqual(len(DownloadNetwork('mirror', 'https://mirror.invalid').sources(URL, HASH)), 1)

    def test_wrong_final_preserved(self):
        self.target.write_bytes(b'private original')
        with self.assertRaises(InstallError): self.download(lambda *a: self.fail('must not fetch'))
        self.assertEqual(self.target.read_bytes(), b'private original')

    def test_disk_space_before_fetch(self):
        disk = MagicMock(); disk.free = 1
        with patch('easy_installer.shutil.disk_usage', return_value=disk), self.assertRaisesRegex(InstallError, '空间'):
            self.download(lambda *a: self.fail('must not fetch'))

    def test_local_mode_does_not_quarantine_bad_partial(self):
        self.partial.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, '禁止自动下载'):
            self.download(lambda *a: self.fail('must not fetch'), network=DownloadNetwork('local'))
        self.assertEqual(self.partial.read_bytes(), b'bad')

    def test_lock_excludes_other_writer_and_releases(self):
        with download_lock(self.target):
            with self.assertRaises(InstallError):
                with download_lock(self.target): self.fail('acquired second lock')
        with download_lock(self.target): pass

    def test_bad_hash_rejected_before_network(self):
        with self.assertRaisesRegex(InstallError, '64位'):
            download_file(URL, self.target, self.logs.append, expected_sha256='wrong')
        self.assertFalse(self.target.exists())

    def test_catalog_all_model_files_pinned_hashed_sized(self):
        root = Path(__file__).resolve().parents[1]
        files = json.loads((root / 'model_catalog.json').read_text('utf-8'))['profiles']['anima-base-1.0']['files']
        for item in json.loads((root / 'optional_components.json').read_text('utf-8'))['components']:
            if item['kind'] == 'download_set': files += item['files']
        for item in files:
            with self.subTest(target=item['target']):
                self.assertRegex(item['url'], r'/resolve/[0-9a-f]{40}/')
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertGreater(item['size'], 0)

    def test_transient_retry_fresh_process_and_http1(self):
        def proc(code, output):
            p = MagicMock(); p.__enter__.return_value = p; p.returncode = code
            p.communicate.return_value = (output, None); return p
        with patch('download_network.subprocess.Popen', side_effect=[proc(92, b'AAA_HTTP:206'), proc(0, b'AAA_HTTP:206')]) as spawn, patch('download_network.time.sleep'):
            fetch_public_file('curl', URL, self.partial, self.logs.append, DownloadNetwork())
        self.assertEqual(spawn.call_count, 2)
        self.assertIn('--http1.1', spawn.call_args.args[0])

    def test_auth_errors_not_retried_or_leaked(self):
        p = MagicMock(); p.__enter__.return_value = p; p.returncode = 22
        p.communicate.return_value = (b'https://signed.invalid/?token=SECRET\nAAA_HTTP:403', None)
        with patch('download_network.subprocess.Popen', return_value=p) as spawn:
            with self.assertRaises(DownloadFailure) as error:
                fetch_public_file('curl', URL, self.partial, self.logs.append, DownloadNetwork())
        self.assertEqual(spawn.call_count, 1)
        self.assertNotIn('SECRET', str(error.exception))


if __name__ == '__main__': unittest.main()
