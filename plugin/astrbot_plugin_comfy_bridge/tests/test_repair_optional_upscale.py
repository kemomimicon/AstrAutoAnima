import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.replay_runtime import hq_replay_job


class RepairChainTests(unittest.IsolatedAsyncioTestCase):
    async def run_chain(self, options):
        tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text(encoding='utf-8'))
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Name) and n.test.id == 'seedvr2_hq')
        fn = ast.parse('async def run(self, options, paths, seed, prompt_id, plan, prompt, event):\n pass').body[0]
        fn.body = branch.body + ast.parse('return plan').body
        ast.fix_missing_locations(fn)
        ns = {'copy': copy, 'WorkflowError': WorkflowError, 'Any': object}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'hq-chain', 'exec'), ns)
        jobs = {'base': {'job_id': 'base', 'input': {'compiled_prompt': 'scene'},
                         'model': {'lora_stack': [{'name': 'role'}]}, 'sampling': {}}}
        calls = []
        async def generate(prompt, opts, **kwargs):
            kind = kwargs['workflow_type']
            calls.append((kind, opts))
            jobs[kind] = {'job_id': kind, 'enhance': {}, 'sampling': {}}
            return ['out.png'], 1, 'prompt', {'job_id': kind, 'enhance': {}}
        store = SimpleNamespace(get_job=lambda ident: copy.deepcopy(jobs[ident]),
                                save_job=lambda j: jobs.update({j['job_id']: j}))
        bridge = SimpleNamespace(config={}, _job_store=lambda: store, _generate=generate)
        plan = await ns['run'](bridge, options, ['base.png'], 1, 'pid', {'job_id': 'base'}, 'scene', None)
        return calls, jobs, plan

    async def test_default_no_repairs_or_upscale(self):
        calls, jobs, plan = await self.run_chain({})
        self.assertEqual(calls, [])
        self.assertEqual(plan['job_id'], 'base')

    async def test_explicit_repairs_without_seedvr2(self):
        calls, jobs, plan = await self.run_chain({'detail_hands': True})
        self.assertEqual([c[0] for c in calls], ['detail_repair_anima_v1'])
        self.assertFalse(jobs[plan['job_id']]['enhance']['detail_upscale'])
        self.assertEqual(calls[0][1]['_restore_lora_stack'], [{'name': 'role'}])

    async def test_explicit_upscale_and_body_selection(self):
        calls, _, _ = await self.run_chain({'detail_upscale': True, 'detail_hands': False,
                                          'detail_feet': False, 'detail_face': True})
        self.assertEqual([c[0] for c in calls], ['detail_repair_anima_v1', 'seedvr2_refine_v1'])
        self.assertFalse(calls[0][1]['detail_hands'])
        self.assertTrue(calls[0][1]['detail_face'])

    async def test_all_disabled_returns_base_without_self_parent(self):
        calls, jobs, plan = await self.run_chain({'detail_hands': False, 'detail_feet': False,
                                                'detail_face': False})
        self.assertEqual(calls, [])
        self.assertEqual(plan['job_id'], 'base')
        self.assertNotIn('hq_base_job_id', jobs['base']['enhance'])

    def test_repair_only_replay_does_not_duplicate_final_detail(self):
        base = {'input': {}, 'model': {}, 'workflow_snapshot': {
            '1': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}},
            '2': {'class_type': 'VAEDecode', 'inputs': {}}}}
        job = {'job_id': 'detail', 'enhance': {'hq_base_job_id': 'base', 'hq_detail_job_id': 'detail'},
               'workflow_snapshot': {
                   '1': {'class_type': 'LoadImage', 'inputs': {'image': 'old.png'}},
                   '2': {'class_type': 'FaceDetailer', 'inputs': {'image': ['1', 0]}},
                   '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        result = hq_replay_job(SimpleNamespace(get_job=lambda ident: base), job)
        self.assertEqual(result['workflow_snapshot']['final_2']['inputs']['image'], ['base_2', 0])
        self.assertEqual(sum(n['class_type'] == 'FaceDetailer' for n in result['workflow_snapshot'].values()), 1)
