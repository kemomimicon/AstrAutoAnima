import unittest
from astr_auto_anima_hub.remote_jobs import _prompt_ids_from_plain, build_remote_command, RemoteJobError, _TargetRecord
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest, DeliveryTarget, RemoteJobImage
from astr_auto_anima_hub.civitai_downloads import DownloadRequest


class FeedbackTests(unittest.TestCase):
    def test_visual_command_and_quoted_role(self):
        target = _TargetRecord(DeliveryTarget(id='private', label='Owner', kind='private'), 'qq:FriendMessage:123456', frozenset({'N'}))
        payload = RemoteJobCreateRequest(target_id='private', kind='direct', character='角色 A', prompt='garden', lighting_key='lighting_golden_hour')
        command, _ = build_remote_command(payload, target)
        self.assertIn('角色="角色 A"', command)
        self.assertTrue(command.endswith('主光=lighting_golden_hour garden'))
        with self.assertRaises(RemoteJobError):
            build_remote_command(payload.model_copy(update={'kind': 'refine', 'profile': 'seedvr2'}), target)

    def test_imported_ids_without_source_prefix(self):
        self.assertEqual(_prompt_ids_from_plain(['好图微批 1-2/5 完成｜条目=G260910_0001,custom.2｜seed=42', '好图 3/5 完成｜条目=0003']), ['G260910_0001', 'custom.2', '0003'])

    def test_default_download_directory(self):
        self.assertEqual(DownloadRequest.model_fields['subdirectory'].default, 'anima_lora')

    def test_image_identity_persists(self):
        data = dict(id='img_1', filename='test.png', size_bytes=1, sha256='a'*64, download_url='/image', prompt_id='G260910_0001')
        image = RemoteJobImage(**data)
        self.assertEqual(RemoteJobImage.model_validate_json(image.model_dump_json()).prompt_id, data['prompt_id'])
