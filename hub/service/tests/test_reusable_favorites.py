import copy
import json
import unittest

from test_actual_image_prompts import ActualImagePrompts
from test_local_jobs import LocalJobsTests
from astr_auto_anima_hub.favorite_text import reusable_text, favorite_task_snapshot
from astr_auto_anima_hub.prompt_snapshots import image_prompt_snapshot
from astr_auto_anima_hub.prompt_favorites import list_favorites
from astr_auto_anima_hub.repositories import RepositoryError


class ReusableText(unittest.TestCase):
    def setUp(self):
        self.fixture = LocalJobsTests()
        self.fixture.setUp()
        self.settings = self.fixture.settings
        self.settings.character_dictionary_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.character_dictionary_path.write_text(json.dumps({'characters': [
            {'tag': 'akasiya', 'aliases': ['艾卡西亚'], 'copyright': ['test game'], 'appearance': ['blue hair']}
        ]}), encoding='utf-8')

    def tearDown(self):
        self.fixture.tearDown()

    def test_filter_preserves_actions_expression_clothing_weights_and_order(self):
        text = r'1girl, solo, akasiya, 艾卡西亚, test_game, (blue_hair:1.2), fox ears, fluffy_tail, blue eyes, pale skin, (akasiya, sitting in cafe:1.1), holding hair, closed eyes, hair ornament, smiling, white dress, <lora:char:1>'
        expected = '1girl, solo, (sitting in cafe:1.1), holding hair, closed eyes, hair ornament, smiling, white dress'
        self.assertEqual(reusable_text(self.settings, text), expected)

    def test_direct_reverse_and_reference_use_base_not_compiled(self):
        for kind in ('quick_txt2img_v1', 'refine_existing_v1', 'snapref_anima_v1'):
            task = {'job_id': 'direct', 'workflow': {'type': kind}, 'input': {
                'prompt': 'akasiya, blue hair, tea garden, sitting, smiling',
                'compiled_prompt': 'akasiya, triggerX, blue hair, watercolor, tea garden, sitting, smiling',
                'preset_snapshot': {'character': {'prompt': 'akasiya, triggerX, blue hair'}}}}
            before = copy.deepcopy(task)
            result = favorite_task_snapshot(self.settings, task)
            self.assertEqual(result['positive'], 'tea garden, sitting, smiling')
            self.assertEqual(task, before)
            self.assertEqual(image_prompt_snapshot(task)['positive'], task['input']['compiled_prompt'])

    def test_modified_remake_keeps_updated_scene_and_exact_addition_once(self):
        task = {'job_id': 'remake', 'input': {
            'source_entries': [{'id': 'pool1', 'prompt': 'moon, sitting, akasiya',
                'user_addition': '', 'original_prompt': 'sun, standing',
                'edit_request': '改为晚上坐着', 'safety_code': 'N'}],
            'compiled_prompt': 'style, akasiya, blue hair, moon, sitting'}}
        self.assertEqual(favorite_task_snapshot(self.settings, task)['positive'], 'moon, sitting')
        task['input']['source_entries'][0].update(prompt='garden', user_addition='rain, blue hair')
        self.assertEqual(favorite_task_snapshot(self.settings, task)['positive'], 'rain, garden')

    def test_upscale_preserves_exact_parent_output_and_rejects_ambiguous_old_job(self):
        parent = {'job_id': 'parent', 'input': {'raw_batch_prompts': ['sun, akasiya', 'moon, akasiya'],
            'batch_prompts': ['sun, akasiya, blue hair', 'moon, akasiya, blue hair']},
            'result': {'assets': ['a', 'b']}}
        child = {'job_id': 'child', 'workflow': {'type': 'seedvr2_refine_v1'}, 'parent_job_id': 'parent',
                 'input': {'source_image_index': 1}}
        result = favorite_task_snapshot(self.settings, child, load_job=lambda _: parent)
        self.assertEqual(result['positive'], 'moon')
        del child['input']['source_image_index']
        with self.assertRaises(RepositoryError):
            favorite_task_snapshot(self.settings, child, load_job=lambda _: parent)

    def test_compiled_only_is_not_guessed_and_empty_after_filter_not_saved(self):
        task = {'input': {'compiled_prompt': 'akasiya, blue hair, garden'}}
        self.assertFalse(favorite_task_snapshot(self.settings, task)['available'])
        task['input']['prompt'] = 'akasiya, blue hair'
        self.assertFalse(favorite_task_snapshot(self.settings, task)['available'])

    def test_refine_of_compiled_parent_does_not_reintroduce_character_or_style(self):
        parent = {'job_id': 'parent', 'input': {'prompt': 'garden, sitting',
            'compiled_prompt': 'triggerX, akasiya, garden, sitting, watercolor'}}
        child = {'job_id': 'refine', 'parent_job_id': 'parent',
                 'workflow': {'type': 'refine_existing_v1'}, 'input': {
                     'prompt': parent['input']['compiled_prompt'],
                     'compiled_prompt': parent['input']['compiled_prompt']}}
        self.assertEqual(favorite_task_snapshot(self.settings, child, load_job=lambda _: parent)['positive'],
                         'garden, sitting')
        child['input']['prompt'] = 'moon, standing, blue hair'
        self.assertEqual(favorite_task_snapshot(self.settings, child, load_job=lambda _: parent)['positive'],
                         'moon, standing')


class ReusableAPI(ActualImagePrompts):
    async def test_character_switch_dedup_cancel_and_actual_view_unmodified(self):
        a = self.image('a', prompt='cafe, sitting, blue hair', addition='rain')
        b = self.image('b', prompt='cafe, sitting, red hair', addition='rain')
        a.final_prompt, b.final_prompt = 'miku, blue hair, cafe, rain', 'asuka, red hair, cafe, rain'
        job = self.job(a, b)
        first = await self.favorite(job, 'a')
        second = await self.favorite(job, 'b')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.json()['action'], 'already_liked')
        self.assertEqual(first.json()['saved_prompt_id'], second.json()['saved_prompt_id'])
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).items[0].prompt,
                         'rain, cafe, sitting')
        self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, ['a', 'b'])
        await self.call('DELETE', '/api/v1/lite/prompt-favorites/' + first.json()['saved_prompt_id'])
        self.assertEqual(self.manager.get(job.id, self.principal).liked_image_ids, [])
        self.assertEqual(a.final_prompt, 'miku, blue hair, cafe, rain')

    async def test_cached_actual_prompt_does_not_bypass_five_draw_base(self):
        self.remote()
        image = self.image('second', prompt_id='', prompt='', safety='')
        image.sha256 = 'b' * 64
        image.final_prompt = 'cached character, moon, style'
        job = self.job(image)
        self.evidence(job)
        result = await self.favorite(job, image.id)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).items[0].prompt,
                         'two, moon')
        self.assertEqual(image.final_prompt, 'cached character, moon, style')

    async def test_compiled_only_old_task_remains_viewable_but_not_favoritable(self):
        self.remote()
        image = self.image('second', prompt_id='', prompt='', safety='')
        image.sha256 = 'b' * 64
        job = self.job(image)
        self.evidence(job)
        path = self.settings.plugin_data_dir / 'job_store/jobs/job_bridge.json'
        task = json.loads(path.read_text())
        del task['input']['raw_batch_prompts']
        path.write_text(json.dumps(task))
        shown = await self.call('GET', f'/api/v1/lite/jobs/{job.id}/images/{image.id}/prompt')
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown.json()['positive'], 'two, moon, character')
        self.assertEqual((await self.favorite(job, image.id)).status_code, 422)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.principal).total, 0)
