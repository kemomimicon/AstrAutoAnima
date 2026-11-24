import base64
import tempfile
import unittest
from pathlib import Path

from astr_auto_anima_hub.remote_jobs import load_delivery_targets, build_remote_command, _decode_source_image, RemoteJobError
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest


class NextJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = Path(self.temp.name) / 'targets.json'
        p.write_text('{"targets":[{"id":"private","label":"Private","kind":"private","umo":"bot:FriendMessage:1","allow_safety":["N"]}]}')
        self.target = load_delivery_targets(p)[0]

    def test_turbo_command_and_reject_bad_cfg(self):
        command, _ = build_remote_command(RemoteJobCreateRequest(target_id='private', kind='turbo', prompt='a park'), self.target)
        self.assertEqual(command, '/aturbo a park')
        with self.assertRaises(RemoteJobError):
            build_remote_command(RemoteJobCreateRequest(target_id='private', kind='turbo', prompt='a park', cfg=6), self.target)

    def test_reference_mode_source_and_conflicts(self):
        p = RemoteJobCreateRequest(target_id='private', kind='reference', prompt='a park', reference_mode='cs')
        self.assertEqual(build_remote_command(p, self.target)[0], '/aref cs a park')
        with self.assertRaises(RemoteJobError):
            _decode_source_image(p)
        from PIL import Image
        import io
        out = io.BytesIO()
        Image.new('RGB', (16,16)).save(out, format='PNG')
        p.source_image_data = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
        p.source_image_name = 'ref.png'
        self.assertEqual(_decode_source_image(p)[0], out.getvalue())
        p.character = 'Alice'
        with self.assertRaises(RemoteJobError):
            build_remote_command(p, self.target)

    def test_multi_preset_lines_preserved(self):
        p = RemoteJobCreateRequest(target_id='private', kind='multi', prompt='预设\n人物1：Alice | | left\n人物2：Bob | | right', ratio='3:2')
        self.assertEqual(build_remote_command(p,self.target)[0], '/amulti 比例=3:2 ' + p.prompt)

    def test_reference_auto_style_and_explicit_all_conflict(self):
        p = RemoteJobCreateRequest(target_id='private',kind='reference',prompt='a park')
        self.assertEqual(build_remote_command(p,self.target)[0], '/aref cs a park')
        p.style = 'Ink style'
        self.assertEqual(build_remote_command(p,self.target)[0], '/aref char 画风="Ink style" a park')
        p.style = '__personal_saved_style'
        p.personal_style_slot = 1
        self.assertIn('/aref char 画风=__personal_saved_style',build_remote_command(p,self.target)[0])
        p.reference_mode = 'cs'
        with self.assertRaises(RemoteJobError): build_remote_command(p,self.target)
