import unittest
from astr_auto_anima_hub.remote_jobs import build_remote_command, _TargetRecord, RemoteJobError, _prompt_ids_from_plain
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest, DeliveryTarget


class RemoteVTests(unittest.TestCase):
    def target(self, kind='private', safety=('N','H','S')):
        return _TargetRecord(DeliveryTarget(id='test', label='test', kind=kind),
                             'bot:FriendMessage:123456', frozenset(safety))

    def test_v_default_and_explicit_private_command(self):
        for pool in ('V', 'V/N', 'V/S'):
            request = RemoteJobCreateRequest(target_id='test', kind='random', pool_filter=pool,
                five_draw=True, character='角色甲', style='水墨', ratio='16:9',
                random_subject_tag='1boy', prompt='sunset')
            command, safety = build_remote_command(request, self.target())
            self.assertEqual(safety, 'N')
            self.assertIn('五连抽 V/N 起手=1boy 角色=角色甲', command)
            self.assertIn('画风=水墨 比例=16:9 sunset', command)
            command, safety = build_remote_command(request, self.target('group', ('N',)))
            self.assertEqual(safety, 'N')

    def test_v_rejects_unsafe_or_unsupported_routes(self):
        for updates, target in [({'pool_filter':'V/H'},self.target()),
                ({'pool_filter':'V/D'},self.target()), ({'kind':'chaos'},self.target()),
                ({'custom_groups':['foo']},self.target()), ({'pool_filter':'V/N/S'},self.target()),
                ({},self.target(safety=('H',)))]:
            request = RemoteJobCreateRequest.model_validate({'target_id':'test','kind':'random','pool_filter':'V',**updates})
            with self.assertRaises(RemoteJobError): build_remote_command(request,target)

    def test_v_ids_roundtrip(self):
        self.assertEqual(_prompt_ids_from_plain(['好图完成｜条目=V:cn-123｜']), ['V:cn-123'])
