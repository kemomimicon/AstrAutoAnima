"""No real installer execution, QQ login or upstream configuration changes."""
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import napcat_setup as nc
from download_network import DownloadNetwork


class NapcatTests(unittest.TestCase):
    def test_default_preparation_is_denied_without_io(self):
        with patch.object(nc, 'download_file') as download, patch.object(nc.tempfile, 'mkdtemp') as mkdir:
            with self.assertRaisesRegex(ValueError, '未确认'):
                nc.prepare('windows', '/unused')
            download.assert_not_called(); mkdir.assert_not_called()

    def test_manifest_is_complete_pinned_https(self):
        for platform, asset in nc.ASSETS.items():
            self.assertTrue(asset['url'].startswith('https://'))
            self.assertIn(asset['version'], asset['url'])
            self.assertRegex(asset['sha256'], r'^[a-f0-9]{64}$')
            self.assertGreater(asset['size'], 0)
        for digest in nc.WINDOWS_FILES.values(): self.assertRegex(digest, r'^[a-f0-9]{64}$')

    def make_zip(self, name, symlink=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            info = zipfile.ZipInfo(name)
            info.filename = name  # Preserve deliberately malformed Windows separators in fixture.
            if symlink: info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, 'test')
        stream.seek(0)
        return stream

    def test_zip_rejects_traversal_windows_devices_and_links_before_writing(self):
        for name in ('../outside', '/absolute', 'C:/bad', 'one\\bad', 'file:stream',
                     'NUL.txt', 'a/COM1.exe', 'dot./bad', 'space /bad', 'a/../../bad', 'bad?.dll'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError): nc.safe_extract(self.make_zip(name), Path(tmp))
                self.assertEqual(list(Path(tmp).iterdir()), [])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): nc.safe_extract(self.make_zip('link', True), Path(tmp))

    def test_zip_duplicate_case_and_existing_target(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('Test.txt', '1'); z.writestr('test.txt', '2')
        stream.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): nc.safe_extract(stream, Path(tmp))
            (Path(tmp) / 'keep.txt').write_text('original')
            with self.assertRaises(ValueError): nc.safe_extract(self.make_zip('keep.txt'), Path(tmp))
            self.assertEqual((Path(tmp) / 'keep.txt').read_text(), 'original')

    def test_local_linux_preparation_preserves_source_and_never_executes(self):
        payload = b'#!/bin/sh\nprintf test\n'
        asset = dict(nc.ASSETS['linux'], size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'local script.sh'; source.write_bytes(payload)
            root = Path(tmp) / 'existing container & new files'
            root.mkdir(); (root / 'qq-state').write_bytes(b'keep')
            with patch.dict(nc.ASSETS, {'linux': asset}), patch.object(nc, 'download_file') as download, patch.object(nc.subprocess, 'Popen') as run:
                result = nc.prepare('linux', str(root), consent=True, local_file=str(source), log=lambda s: None)
                self.assertEqual(result.read_bytes(), payload)
                self.assertEqual(source.read_bytes(), payload)
                self.assertEqual((root / 'qq-state').read_bytes(), b'keep')
                command = nc.linux_install_command(result)
                self.assertIn('--docker n --cli y --github-proxy 0', command)
                self.assertNotIn('--force', command)
                self.assertIn("'", command)
                download.assert_not_called(); run.assert_not_called()

    def test_wrong_local_hash_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'fake.zip'; source.write_bytes(b'not official')
            target = Path(tmp) / 'new'
            with self.assertRaises(ValueError): nc.prepare('windows', str(target), consent=True, local_file=str(source))
            self.assertFalse(target.exists()); self.assertTrue(source.exists())

    def test_local_mode_forbids_network_without_cached_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch('download_network.fetch_public_file') as fetch:
            with self.assertRaisesRegex(ValueError, '本地文件模式'):
                nc.prepare('linux', str(Path(tmp) / 'new'), consent=True, network=DownloadNetwork('local'))
            fetch.assert_not_called()

    def test_installer_needs_consent_and_revalidation(self):
        with patch.object(nc.subprocess, 'Popen') as run:
            with self.assertRaises(ValueError): nc.launch_installer('not-an-exe')
            run.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / 'NapCatInstaller.exe'; entry.write_bytes(b'fake')
            with patch.object(nc, 'platform_name', return_value='windows'), patch.object(nc.subprocess, 'Popen') as run:
                with self.assertRaises(ValueError): nc.launch_installer(entry, confirmed=True)
                run.assert_not_called()

    def test_installer_uses_argv_not_shell_and_user_selected_cwd(self):
        with tempfile.TemporaryDirectory(prefix='napcat & ') as tmp:
            entry = Path(tmp) / 'NapCatInstaller.exe'; entry.write_bytes(b'fixture')
            with patch.object(nc, 'platform_name', return_value='windows'), patch.object(nc, 'verify_windows_tree') as verify, patch.object(nc.subprocess, 'Popen') as run:
                nc.launch_installer(entry, confirmed=True)
                verify.assert_called_once_with(entry.parent)
                run.assert_called_once_with([str(entry.resolve())], cwd=str(entry.parent.resolve()))

    def test_no_remote_or_credential_bearing_urls(self):
        for url in ('https://example.com', 'http://192.168.1.2:6099', 'http://127.0.0.1:6099/webui',
                    'http://user@127.0.0.1:6099', 'http://127.0.0.1:6099?token=private',
                    'http://localhost:0', 'http://localhost:bad', 'http://localhost/#token'):
            with self.subTest(url=url), self.assertRaises(ValueError): nc.local_url(url)
        self.assertEqual(nc.local_url(' http://127.0.0.1:6099/ '), 'http://127.0.0.1:6099')

    def test_no_login_without_explicit_consent(self):
        with patch.object(nc, 'api_call') as call:
            with self.assertRaises(ValueError): nc.check_login('http://localhost:6099', 'fixture')
            call.assert_not_called()

    def test_login_state_is_separate_from_onebot_and_no_qq_mutation(self):
        fixtures = [({'isLogin': True}, 'QQ 已登录'), ({'isLogin': True, 'isOffline': True}, 'QQ 已掉线'),
                    ({'isLogin': False}, 'QQ 未登录'), ({}, '未返回可识别')]
        for state, text in fixtures:
            with patch.object(nc, 'api_call', side_effect=[{'Credential': 'fixture-session'}, state]) as call:
                result = nc.check_login('http://localhost:6099', 'fixture-token', consent=True)
                self.assertIn(text, result)
                self.assertEqual([x.args[1] for x in call.call_args_list], ['/auth/login', '/QQLogin/CheckLoginStatus'])
                self.assertEqual(call.call_args_list[0].args[2]['hash'], hashlib.sha256(b'fixture-token.napcat').hexdigest())
                self.assertNotIn('fixture', result)

    def test_2fa_is_respected(self):
        with patch.object(nc, 'api_call', return_value={'require2FA': True}) as call:
            self.assertIn('双重验证', nc.check_login('http://localhost:6099', 'fixture', consent=True))
            self.assertEqual(call.call_count, 1)

    def test_no_redirect_or_proxy_or_unapproved_api(self):
        redirect = nc.NoRedirect()
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://outside.invalid'))
        with self.assertRaises(ValueError): nc.api_call('http://localhost:6099', '/QQLogin/SetQuickLogin', {})
        response = Mock(); response.read.return_value = json.dumps({'code': 0, 'data': {'ok': True}}).encode()
        opener = Mock(); opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(nc.urllib.request, 'build_opener', return_value=opener) as build:
            self.assertEqual(nc.api_call('http://localhost:6099', '/QQLogin/CheckLoginStatus', {}, 'fixture'), {'ok': True})
            self.assertEqual(build.call_args.args[0].proxies, {})

    def test_port_probe_never_claims_protocol_connected(self):
        for port in ('0', '65536', '-1', 'abc', '6199/ws'):
            with self.assertRaises(ValueError): nc.onebot_values(port)
        self.assertEqual(nc.onebot_values(), 'ws://127.0.0.1:6199/ws')
        connection = Mock(); connection.__enter__ = Mock(); connection.__exit__ = Mock()
        with patch.object(nc.socket, 'create_connection', return_value=connection):
            self.assertIn('不能证明', nc.probe_listener('6199'))
        with patch.object(nc.socket, 'create_connection', side_effect=OSError):
            self.assertIn('未连通', nc.probe_listener('6199'))


if __name__ == '__main__': unittest.main()
