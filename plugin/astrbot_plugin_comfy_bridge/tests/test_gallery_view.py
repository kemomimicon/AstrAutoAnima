import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from astrbot_plugin_comfy_bridge.gallery_view_runtime import gallery_view
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_body


class GalleryReadTests(unittest.TestCase):
    def test_missing_does_not_create_or_generate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(gallery_view(root)[1], [])
            self.assertEqual(list(root.iterdir()), [])

    def test_list_match_four_previews_missing_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gallery = root / 'style_gallery'
            gallery.mkdir()
            slots = [{'index': i, 'status': 'succeeded', 'file': f'{i:032x}.image'} for i in range(4)]
            data = {'items': [{'style': '柔光画风', 'slots': slots}]}
            manifest = gallery / 'gallery.json'
            manifest.write_text(json.dumps(data), encoding='utf-8')
            for slot in slots: (gallery / slot['file']).write_bytes(b'preview')
            self.assertIn('柔光画风', gallery_view(root)[0])
            text, images = gallery_view(root, '画风="柔光画风"')
            self.assertEqual(len(images), 4)
            self.assertIn('水上秋千', images[0][0])
            self.assertEqual(len(gallery_view(root, '柔光')[1]), 4)
            with self.assertRaises(WorkflowError): gallery_view(root, '页=2')
            with self.assertRaises(WorkflowError): gallery_view(root, '不存在')
            slots[0]['status'] = 'failed'
            manifest.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(len(gallery_view(root, '柔光')[1]), 3)
            slots[0].update(status='succeeded', file='../secret')
            manifest.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(WorkflowError): gallery_view(root, '柔光')

    def test_ambiguous_names_only_return_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'style_gallery').mkdir()
            (root/'style_gallery/gallery.json').write_text(json.dumps({'items':[
                {'style':'画风A','slots':[]},{'style':'画风B','slots':[]}]}))
            text, images=gallery_view(root,'画风')
            self.assertIn('匹配多个',text)
            self.assertEqual(images,[])


class GalleryDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_images_respect_current_safety_without_generation_or_penalty(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='agallery')
        method.decorator_list=[]
        ns={'__package__':'astrbot_plugin_comfy_bridge','AstrMessageEvent':object,'extract_command_body':extract_command_body}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'gallery','exec'),ns)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'style_gallery').mkdir()
            (root/'style_gallery/gallery.json').write_text(json.dumps({'items':[{'style':'A','slots':[
                {'index':0,'status':'succeeded','file':'a'*32+'.image'}]}]}))
            (root/'style_gallery'/('a'*32+'.image')).write_bytes(b'image')
            bridge=SimpleNamespace(_character_dictionary_path=lambda:root/'dictionary.json',
                _safety_policy=lambda:SimpleNamespace(enabled=True,fingerprint='new'),
                _safety_store=SimpleNamespace(approved=Mock(return_value=False)))
            event=SimpleNamespace(message_str='查看画廊 A',stop_event=Mock(),should_call_llm=Mock(),
                plain_result=lambda text:('text',text),image_result=lambda path:('image',path),send=AsyncMock())
            await ns['agallery'](bridge,event)
            self.assertTrue(all(call.args[0][0]=='text' for call in event.send.await_args_list))
            self.assertTrue(any('不会扣除' in call.args[0][1] for call in event.send.await_args_list))
            bridge._safety_store.approved.return_value=True
            event.send.reset_mock()
            await ns['agallery'](bridge,event)
            self.assertEqual(sum(call.args[0][0]=='image' for call in event.send.await_args_list),1)
