import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import build_platform_full_suites as builder


def zipped(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as arc:
        for name,data in entries.items():
            item=zipfile.ZipInfo('placeholder');item.filename=name;item.orig_filename=name
            arc.writestr(item,data)
    return stream.getvalue()


class PlatformFullTests(unittest.TestCase):
    def setUp(self):
        self.base={'BUILD_REPORT.json':b'{}','offline-acceptance.json':b'{}',
                   'components/plugin.zip':b'unchanged-component',
                   'clients/windows/admin.zip':b'unchanged-admin',
                   'clients/android/service.apk':b'unchanged-phone',
                   'deployment/old-other.zip':b'not-selected',
                   'first-run-guide/old.txt':b'outdated-guide',
                   'source/old.zip':b'old-source'}
        for platform in ['windows','linux']:
            entry='Deploy-Windows.cmd' if platform=='windows' else 'Deploy-Linux.sh'
            files={n:b'public' for n in ['.astr_auto_anima_public_root',entry,'tools/setup_center.py',
                   'tools/deploy_project.py','tools/deployment_support.py','tools/model_catalog.json','hub/service/web/index.html']}
            self.base[f'deployment/AstrAutoAnima-lazy-bundle-{platform}-0.5.2-beta.1.zip']=zipped({'root/'+n:d for n,d in files.items()})
        self.source=zipped({'root/docs/platform-full/windows.md':b'# Windows\n```cmd\necho test\n```',
                            'root/docs/platform-full/linux.md':b'# Linux\n```bash\necho test\n```',
                            'root/docs/TOOLS.md':b'public tools'})

    def test_independent_correct_platform_installers_and_common_clients(self):
        for platform,entry,other in [('windows','Install-Windows.cmd','Install-Linux.sh'),('linux','Install-Linux.sh','Install-Windows.cmd')]:
            with self.subTest(platform=platform):
                result=builder.assemble(self.base,platform,self.source,'a'*40)
                self.assertIn(entry,result);self.assertNotIn(other,result)
                self.assertIn('installer/hub/service/web/index.html',result)
                self.assertNotIn('deployment/old-other.zip',result)
                self.assertNotIn('first-run-guide/old.txt',result)
                self.assertEqual(result['components/plugin.zip'],b'unchanged-component')
                self.assertEqual(result['clients/windows/admin.zip'],b'unchanged-admin')
                self.assertEqual(result['clients/android/service.apk'],b'unchanged-phone')

    def test_manifest_covers_and_hashes_every_payload(self):
        result=builder.assemble(self.base,'linux',self.source,'a'*40)
        manifest=json.loads(result['suite-manifest.json'])
        self.assertEqual({r['path'] for r in manifest['files']},set(result)-{'suite-manifest.json'})
        for row in manifest['files']:
            self.assertEqual(row['size'],len(result[row['path']]))
            self.assertEqual(row['sha256'],hashlib.sha256(result[row['path']]).hexdigest())
        self.assertFalse(manifest['private_data_included'])

    def test_incomplete_installer_rejected(self):
        self.base['deployment/AstrAutoAnima-lazy-bundle-linux-0.5.2-beta.1.zip']=zipped({'root/Deploy-Linux.sh':b'echo test'})
        with self.assertRaises(ValueError):builder.assemble(self.base,'linux',self.source,'a'*40)

    def test_path_traversal_backslashes_streams_and_case_duplicates_rejected(self):
        for names in [{'../outside':b'x'},{'/absolute':b'x'},{'root/a:b':b'x'},{'root\\escape':b'x'},{'root/A':b'x','root/a':b'y'}]:
            with self.subTest(names=list(names)),self.assertRaises(ValueError):builder.read_zip(zipped(names))

    def test_wrong_published_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong.zip';p.write_bytes(zipped({'root/a':b'x'}))
            with self.assertRaises(ValueError):builder.load_baseline(p)

    def test_tampered_baseline_member_is_rejected(self):
        payload=zipped({'root/a':b'changed','root/suite-manifest.json':json.dumps({'files':[{'path':'a','size':1,'sha256':'0'*64}]}).encode()})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.zip';p.write_bytes(payload)
            with patch.object(builder,'BASE_SHA',builder.sha(payload)),self.assertRaises(ValueError):builder.load_baseline(p)

    def test_html_offline_and_commands_are_escaped(self):
        rendered=builder.render_guide('# Test\n```bash\necho "<safe>"\n```','Linux').decode()
        self.assertIn('&lt;safe&gt;',rendered)
        self.assertIn('复制代码',rendered)
        self.assertNotIn('<script src=',rendered)
        with self.assertRaises(ValueError):builder.render_guide('```bash\nunclosed','Linux')

    def test_windows_entry_ascii_linux_entry_lf(self):
        win=builder.assemble(self.base,'windows',self.source,'a'*40)
        linux=builder.assemble(self.base,'linux',self.source,'a'*40)
        self.assertTrue(win['Install-Windows.cmd'].isascii())
        self.assertIn(b'"%~dp0installer"',win['Install-Windows.cmd'])
        self.assertNotIn(b'\r',linux['Install-Linux.sh'])
        self.assertIn(b'"$@"',linux['Install-Linux.sh'])


if __name__=='__main__':unittest.main()
