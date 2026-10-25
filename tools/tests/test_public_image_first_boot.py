import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import tarfile
import hashlib

spec=importlib.util.spec_from_file_location('image_first_boot',Path(__file__).resolve().parents[1] / 'autodl_image_052144/first_boot.py')
boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)


class FirstBootTests(unittest.TestCase):
    def create(self, base):
        root=base/'aaa-install'; defaults=root/'.image-defaults';defaults.mkdir(parents=True)
        (defaults/'templates.json').write_text(json.dumps({'env_full':{'AAH_ASTRBOT_API_KEY':''},'env_local':{},'astrbot':{'dashboard':{}}}))
        return root,base/'napcat/config/webui.json'

    def test_separate_clones_have_unique_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            roots=[]
            for name in ['a','b']:
                root,nap=self.create(Path(tmp)/name);boot.initialize(root,Path(tmp),nap)
                roots.append(json.loads((root/'INITIAL_CREDENTIALS.json').read_text()))
                env=json.loads((root/'runtime-env.full.json').read_text())
                self.assertEqual(env['AAH_ASTRBOT_API_KEY'],'')
                self.assertEqual(env['AAH_ADMIN_TOKEN'],roots[-1]['hub_admin_token'])
                astro=json.loads((root/'astrbot/data/cmd_config.json').read_text())
                self.assertTrue(astro['dashboard']['password_change_required'])
                self.assertNotEqual(astro['dashboard']['password'],roots[-1]['astrbot_initial_password'])
            for field in ['hub_admin_token','hub_local_admin_token','astrbot_initial_password','napcat_webui_token','onebot_token_pending_manual_setup']:
                self.assertNotEqual(roots[0][field],roots[1][field]);self.assertNotIn(roots[0][field],out.getvalue())

    def test_rerun_refuses_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root,nap=self.create(Path(tmp));boot.initialize(root,Path(tmp),nap)
            before=(root/'INITIAL_CREDENTIALS.json').read_bytes()
            with self.assertRaises(ValueError):boot.initialize(root,Path(tmp),nap)
            self.assertEqual(before,(root/'INITIAL_CREDENTIALS.json').read_bytes())

    def test_existing_napcat_refused_before_credentials_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,nap=self.create(Path(tmp));nap.parent.mkdir(parents=True);nap.write_text('{}')
            with self.assertRaises(ValueError):boot.initialize(root,Path(tmp),nap)
            self.assertFalse((root/'INITIAL_CREDENTIALS.json').exists())

    def test_unsafe_archive_entries_rejected(self):
        for name in ['../escape','/root/escape','autodl-tmp/../escape','other/file']:
            self.assertFalse(boot.allowed_member(tarfile.TarInfo(name)))
        good=tarfile.TarInfo('autodl-tmp/aaa-install/code.py');self.assertTrue(boot.allowed_member(good))
        link=tarfile.TarInfo('autodl-tmp/link');link.type=tarfile.SYMTYPE;link.linkname='/etc/shadow'
        self.assertFalse(boot.allowed_member(link))
        link.linkname='../.ssh/authorized_keys'
        self.assertFalse(boot.allowed_member(link))

    def test_real_stream_extraction_with_internal_links(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            base=Path(temp)/'autodl-tmp';base.mkdir();image=Path(temp)/'image';image.mkdir()
            archive=image/'runtime.tar.gz';data=b'fixture-not-a-model'
            with tarfile.open(archive,'w:gz') as tar:
                regular=tarfile.TarInfo('autodl-tmp/example/a');regular.size=len(data);regular.mode=0o755
                tar.addfile(regular,io.BytesIO(data))
                hard=tarfile.TarInfo('autodl-tmp/example/b');hard.type=tarfile.LNKTYPE;hard.linkname='autodl-tmp/example/a';tar.addfile(hard)
                soft=tarfile.TarInfo('autodl-tmp/example/c');soft.type=tarfile.SYMTYPE;soft.linkname='a';tar.addfile(soft)
            (image/'payload-manifest.json').write_text(json.dumps({'top_roots':['example'],'unique_bytes':len(data),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
            boot.extract(image,base)
            self.assertEqual((base/'example/c').read_bytes(),data)
            self.assertEqual((base/'example/a').stat().st_ino,(base/'example/b').stat().st_ino)


if __name__=='__main__':unittest.main()
