import json
from types import SimpleNamespace
import test_kp_lora_personal as fixtures
from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.prompt_likes import promote_k_prompt, remove_prompt_favorite
from astr_auto_anima_hub.prompt_reports import PromptReports
from astr_auto_anima_hub.repositories import list_prompts, RepositoryError


class PromptSocialTests(fixtures.KpLoraPersonalTests):
    def _reports_for(self, prompt_id, prompt_ids):
        path = self.settings.hub_state_dir / 'report-test.png'
        path.write_bytes(b'image-evidence')
        image = SimpleNamespace(id='img', content_type='image/png', sha256='hash', prompt_id=prompt_id)
        job = SimpleNamespace(images=[image], prompt_ids=prompt_ids, command_preview='/aimg')
        jobs = SimpleNamespace(get=lambda j,p: job, get_image=lambda j,i,p: (image,path), _require_approved=lambda b: None)
        return PromptReports(self.settings, jobs)

    def test_non_k_report_uses_image_id_not_task_list_position(self):
        reports = self._reports_for('good-001', ['wrong-id'])
        result = reports.submit('job', 'img', self.user)
        self.assertEqual(reports.list()['items'][0]['prompt_id'], 'good-001')
        reports.resolve(result['id'], 'trash', AuthPrincipal(role='admin', subject='admin'))
        data = json.loads(self.settings.prompt_pool_path.read_text())
        target = next(r for r in data['prompts'] if r['id'] == 'good-001')
        self.assertFalse(target['enabled'])
        self.assertEqual(data['trash'][0]['id'], 'good-001')

    def test_missing_mapping_can_report_but_cannot_trash(self):
        reports = self._reports_for('', ['first', 'second'])
        result = reports.submit('job', 'img', self.user)
        admin = AuthPrincipal(role='admin', subject='admin')
        self.assertEqual(reports.list()['items'][0]['prompt_id'], '')
        with self.assertRaises(RepositoryError):
            reports.resolve(result['id'], 'trash', admin)
        self.assertEqual(reports.resolve(result['id'], 'dismiss', admin)['status'], 'dismiss')

    def test_general_favorite_private_and_remove(self):
        favorite = promote_k_prompt(self.settings, 'good-001', self.user)
        own = list_prompts(self.settings.prompt_pool_path, source='P', owner=self.user.subject)
        self.assertEqual(len(own.items),1)
        other = AuthPrincipal(role='user',subject='other',qq='777777')
        self.assertEqual(list_prompts(self.settings.prompt_pool_path,source='P',owner=other.subject).total,0)
        remove_prompt_favorite(self.settings, favorite.saved_prompt_id, other)
        self.assertEqual(list_prompts(self.settings.prompt_pool_path,source='P',owner=self.user.subject).total,1)
        remove_prompt_favorite(self.settings, favorite.saved_prompt_id, self.user)
        self.assertEqual(list_prompts(self.settings.prompt_pool_path,source='P',owner=self.user.subject).total,0)
        self.assertEqual(list_prompts(self.settings.prompt_pool_path,source='B').total,1)

    def test_report_evidence_dedup_and_admin_decision(self):
        image_path = self.settings.hub_state_dir/'test.png'
        image_path.write_bytes(b'passed-image')
        image = SimpleNamespace(id='img',content_type='image/png',sha256='hash')
        job = SimpleNamespace(images=[image],prompt_ids=['kp-h01-safe'],command_preview='K/N')
        jobs = SimpleNamespace(get=lambda j,p: job if p==self.user else None,
            get_image=lambda j,i,p: (image,image_path) if p==self.user else None,
            _require_approved=lambda content: None)
        reports = PromptReports(self.settings,jobs)
        result=reports.submit('job','img',self.user)
        self.assertEqual(reports.submit('job','img',self.user)['id'],result['id'])
        with self.assertRaises(RepositoryError):
            reports.submit('job','img',AuthPrincipal(role='user',subject='other'))
        image_path.write_bytes(b'changed')
        self.assertEqual(reports.image(result['id'])[0].read_bytes(),b'passed-image')
        with self.assertRaises(RepositoryError):
            reports.resolve(result['id'],'trash',self.user)
        admin=AuthPrincipal(role='admin',subject='admin')
        self.assertEqual(reports.resolve(result['id'],'trash',admin)['status'],'trash')
        data=json.loads(self.settings.kp_prompt_pool_path.read_text())
        self.assertFalse(data['prompts'][0]['enabled'])
        self.assertEqual(len(data['trash']),1)
        reports.resolve(result['id'],'trash',admin)
        self.assertEqual(len(json.loads(self.settings.kp_prompt_pool_path.read_text())['trash']),1)
