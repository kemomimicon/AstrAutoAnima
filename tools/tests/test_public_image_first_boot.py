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
    def layers(self, temp):
        base=Path(temp)/'autodl-tmp';base.mkdir();image=Path(temp)/'image';image.mkdir()
        data=b'public-resource-fixture'
        archive=image/'runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            item=tarfile.TarInfo('autodl-tmp/example/shared');item.size=len(data)
            tar.addfile(item,io.BytesIO(data))
        extra=image/'public-resources.tar.gz'
        with tarfile.open(extra,'w:gz') as tar:
            item=tarfile.TarInfo('autodl-tmp/example/alias');item.type=tarfile.LNKTYPE
            item.linkname='autodl-tmp/example/shared';tar.addfile(item)
        manifest={'top_roots':['example'],'unique_bytes':len(data),'sha256':boot.sha256(archive),
                  'extra_archives':[{'file':extra.name,'sha256':boot.sha256(extra),'entries':1}]}
        (image/'payload-manifest.json').write_text(json.dumps(manifest))
        return base,image,manifest

    def test_public_resource_alias_links_to_verified_base_archive(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            base,image,_=self.layers(temp);boot.extract(image,base)
            self.assertEqual((base/'example/alias').read_bytes(),b'public-resource-fixture')
            self.assertEqual((base/'example/alias').stat().st_ino,(base/'example/shared').stat().st_ino)

    def test_all_archive_hashes_are_checked_before_writing(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            base,image,manifest=self.layers(temp)
            manifest['extra_archives'][0]['sha256']='0'*64
            (image/'payload-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):boot.extract(image,base)
            self.assertFalse((base/'example').exists())

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
