import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from download_network import DownloadNetwork, failure_message, fetch_public_file
from easy_installer import download_file, InstallError
from deployment_support import install_anima_master, AM_COMMIT
from deploy_project import copy_source, Plan, validate

HASH = hashlib.sha256(b'complete').hexdigest()


class DownloadTests(unittest.TestCase):
    def test_official_default_and_mirror_routes(self):
        url = 'https://huggingface.co/org/repo/resolve/main/model?download=true'
        self.assertEqual(DownloadNetwork().source(url, HASH), url)
        network = DownloadNetwork('mirror', 'https://hf.example.invalid', 'https://gh.example.invalid/files')
        self.assertEqual(network.source(url, HASH), url.replace('huggingface.co', 'hf.example.invalid'))
        github = 'https://codeload.github.com/owner/repo/zip/commit'
        self.assertEqual(network.source(github, HASH), 'https://gh.example.invalid/files/' + github)
        other = 'https://example.invalid/file'
        self.assertEqual(network.source(other, ''), other)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            network.source(url, '')

    def test_endpoint_secrets_and_insecure_mirrors_rejected(self):
        for endpoint in ('http://mirror.invalid', 'https://user:secret@mirror.invalid',
                         'https://mirror.invalid?token=secret', 'https://mirror.invalid/#x',
                         'https://mirror.invalid/white space', 'https://mirror.invalid:bad',
                         'https://mirror.invalid\\path'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                DownloadNetwork('mirror', endpoint).validate()
        with self.assertRaises(ValueError):
            DownloadNetwork('proxy', proxy='http://user:secret@localhost:7890').validate()
        with self.assertRaises(ValueError):
            DownloadNetwork('proxy').validate()
        DownloadNetwork('proxy', proxy='socks5h://127.0.0.1:7890').validate()

    def test_local_mode_rejects_network_and_incomplete_plan(self):
        with self.assertRaisesRegex(ValueError, '禁止自动下载'):
            DownloadNetwork('local').source('https://example.invalid/file', HASH)
        with self.assertRaisesRegex(ValueError, '选齐'):
            validate(Plan('unused', download_mode='local', download_models=True))

    def test_failure_classification(self):
        self.assertIn('超时', failure_message(28, 'timeout'))
        self.assertIn('吊销', failure_message(35, 'CRYPT_E_REVOCATION_OFFLINE (0x80092013)'))
        self.assertIn('不会关闭', failure_message(60, 'invalid cert'))
        self.assertIn('断点续传', failure_message(22, 'HTTP 416'))
        self.assertIn('HTTP', failure_message(22, 'HTTP 403'))

    def test_curl_args_bound_retry_and_no_tls_bypass(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired('curl', 15), (b'', None)]
        log = []
        with patch('download_network.subprocess.Popen', return_value=process) as spawn:
            fetch_public_file('curl', 'https://example.invalid/file', Path('not-present.part'), log.append,
                              DownloadNetwork('proxy', proxy='http://127.0.0.1:7890'))
        args = spawn.call_args.args[0]
        self.assertEqual(args[1], '--disable')
        self.assertEqual(args[args.index('--retry') + 1], '2')
        self.assertEqual(args[args.index('--proto-redir') + 1], '=https')
        self.assertEqual(args[args.index('--proxy') + 1], 'http://127.0.0.1:7890')
        for forbidden in ('-k', '--insecure', '--ssl-no-revoke', '--ssl-revoke-best-effort', '--location-trusted'):
            self.assertNotIn(forbidden, args)
        self.assertTrue(any('0.0 MiB' in item for item in log))

    def test_curl_failure_is_actionable(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 35
        process.communicate.return_value = (b'CRYPT_E_REVOCATION_OFFLINE', None)
        with patch('download_network.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '证书吊销检查'):
                fetch_public_file('curl', 'https://example.invalid/file', Path('missing.part'), lambda _: None, DownloadNetwork())

    def test_explicit_schannel_opt_in_only(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 0
        process.communicate.return_value = (b'', None)
        with (patch('download_network.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'curl Schannel', '')),
              patch('download_network.subprocess.Popen', return_value=process) as spawn):
            fetch_public_file('curl', 'https://example.invalid/file', Path('missing.part'), lambda _: None,
                              DownloadNetwork(revoke_best_effort=True))
        self.assertIn('--ssl-revoke-best-effort', spawn.call_args.args[0])

    def test_hash_mismatch_never_promoted_and_partial_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'model'
            def fake_fetch(curl, source, partial, log, network):
                partial.write_bytes(b'wrong')
            with patch('easy_installer.shutil.which', return_value='curl'), patch('download_network.fetch_public_file', side_effect=fake_fetch):
                with self.assertRaisesRegex(InstallError, 'SHA256'):
                    download_file('https://example.invalid/file', target, lambda _: None, expected_sha256=HASH)
            self.assertFalse(target.exists())
            self.assertEqual(target.with_name('model.part').read_bytes(), b'wrong')

    def test_complete_partial_and_final_skip_curl_even_local(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'model'
            target.with_name('model.part').write_bytes(b'complete')
            with patch('download_network.fetch_public_file') as fetch:
                for _ in range(2):
                    download_file('https://example.invalid/file', target, lambda _: None,
                                  expected_sha256=HASH, network=DownloadNetwork('local'))
                fetch.assert_not_called()
            self.assertEqual(target.read_bytes(), b'complete')

    def test_local_am_import_hash_and_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'local.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                prefix = 'anima-master-' + AM_COMMIT + '/'
                z.writestr(prefix + 'metadata.yaml', 'version: 0.7.1')
                z.writestr(prefix + 'main.py', '# fixture')
            with patch('deployment_support.AM_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), patch('easy_installer.download_file') as download:
                target = install_anima_master(root / 'astro', root, lambda _: None, copy_source,
                                              local_archive=str(archive), network=DownloadNetwork('local'))
                download.assert_not_called()
                self.assertTrue((target / 'main.py').is_file())
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                install_anima_master(root / 'other', root, lambda _: None, copy_source, local_archive=str(archive))


if __name__ == '__main__':
    unittest.main()
