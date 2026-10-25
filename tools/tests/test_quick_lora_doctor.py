import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quick_lora_doctor as d

FIXED = b'def _slotless_style_sources(*args): return []\ndef apply_lora_plan(): return _slotless_style_sources()\n'


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())


def fixture(base):
    plugin = base / 'astrbot/data/plugins' / d.PLUGIN
    put(plugin / 'preset_runtime.py', FIXED)
    put(plugin / 'metadata.yaml', b'version: 0.5.0-beta.2\n')
    flow = base / 'ComfyUI/Quick.json'
    graph = {'1': {'class_type': 'UNETLoader', 'inputs': {}},
             '2': {'class_type': 'CLIPLoader', 'inputs': {}},
             '19': {'class_type': 'KSampler', 'inputs': {'model': ['1', 0]}},
             '11': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': 'PRIVATE-PROMPT'}},
             '12': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0]}}}
    put(flow, graph)
    cfg = {'workflow_path': str(flow), 'style_lora_mode': 'dynamic', 'style_lora_node_ids': '', 'api_key': 'PRIVATE-KEY'}
    put(plugin.parent.parent / 'config' / (d.PLUGIN + '_config.json'), cfg)
    return plugin, graph, cfg


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='AAA doctor 中文 '); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.plugin, self.graph, self.cfg = fixture(self.root)

    def test_automatic_candidates_and_stale_managed_root(self):
        for directory in (self.root, self.root/'astrbot', self.root/'astrbot/data', self.plugin):
            self.assertEqual(d.candidates(directory), [self.plugin])
        managed = self.root / 'other'
        put(managed / 'services.json', [{'name': 'AstrBot', 'cwd': str(self.root/'astrbot'), 'command': ['PRIVATE-KEY']}])
        self.assertEqual(d.candidates(managed), [self.plugin])

    def test_old_branch_detected_even_if_new_helper_is_unused(self):
        content = "def apply_lora_plan():\n raise ValueError(" + repr(d.OLD_ERROR) + ")\n"
        put(self.plugin/'preset_runtime.py', content.encode())
        self.assertEqual(d.patch_state(self.plugin/'preset_runtime.py')[0], 'old')
        rows = d.diagnose(self.plugin)
        self.assertTrue(any(r.level=='FAIL' and '旧版' in r.title for r in rows))

    def test_fixed_function_requires_real_call_not_comment(self):
        self.assertEqual(d.patch_state(self.plugin/'preset_runtime.py')[0], 'fixed')
        put(self.plugin/'preset_runtime.py', b'# _slotless_style_sources\ndef apply_lora_plan(): pass\n')
        self.assertEqual(d.patch_state(self.plugin/'preset_runtime.py')[0], 'unknown')

    def test_actual_public_runtime_contains_fix(self):
        public = Path(__file__).resolve().parents[2] / 'plugin' / d.PLUGIN / 'preset_runtime.py'
        if not public.is_file(): self.skipTest('Standalone doctor package intentionally contains no plugin payload')
        self.assertEqual(d.patch_state(public)[0], 'fixed')

    def test_diagnosis_read_only_and_does_not_expose_keys_or_prompts(self):
        put(self.root/'models/private.safetensors', b'UNCHANGED')
        put(self.root/'runtime-env.json', b'not-json-do-not-read-PRIVATE-KEY')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = d.format_report(d.diagnose(self.plugin))
        self.assertNotIn('PRIVATE-KEY', report); self.assertNotIn('PRIVATE-PROMPT', report)
        self.assertIn('磁盘包含 Quick 热修', report)
        self.assertNotIn('[FAIL]', report)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_no_lora_dynamic_and_fixed_empty_configuration(self):
        self.assertTrue(any(r.level=='PASS' for r in d.graph_findings(self.graph, self.cfg)))
        self.cfg['style_lora_mode']='fixed'
        self.assertTrue(any(r.level=='FAIL' for r in d.graph_findings(self.graph, self.cfg)))

    def test_bad_slots_and_clip_mismatch(self):
        self.cfg['style_lora_node_ids']='19'
        self.assertTrue(any('类型' in r.title and r.level=='FAIL' for r in d.graph_findings(self.graph,self.cfg)))
        self.cfg['style_lora_node_ids']=''
        self.graph['12']['inputs']['clip']=['1',0]
        self.assertTrue(any(r.level=='FAIL' and '接线' in r.title for r in d.graph_findings(self.graph,self.cfg)))

    def test_editor_json_unknown_class_and_partial_slots(self):
        self.assertEqual(d.graph_findings({'nodes': []}, self.cfg)[0].level, 'FAIL')
        self.graph['46']={'class_type':'LoraLoader', 'inputs':{}}
        self.cfg['style_lora_node_ids']='46,47'
        self.assertTrue(any(r.level=='FAIL' for r in d.graph_findings(self.graph,self.cfg)))

    def test_unknown_config_requires_manual_confirmation(self):
        (self.plugin.parent.parent / 'config' / (d.PLUGIN+'_config.json')).unlink()
        rows = d.diagnose(self.plugin, str(self.root/'ComfyUI/Quick.json'))
        self.assertTrue(any(r.title=='仅结构检查' and r.level=='WARN' for r in rows))

    def test_invalid_python_does_not_execute(self):
        put(self.plugin/'preset_runtime.py', b'import os\nos._exit(91)\ndef broken(\n')
        rows = d.diagnose(self.plugin)
        self.assertTrue(any(r.level=='FAIL' for r in rows))

    @unittest.skipUnless(os.name=='nt', 'Windows process clues')
    def test_process_check_never_reports_commandline_or_raw_error(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([{'pid':3, 'exe':'example/python.exe', 'CommandLine':'PRIVATE-KEY'}]).encode(), b'')
        with patch.object(d.subprocess,'run',return_value=result): report=d.format_report(d.process_clues(self.plugin))
        self.assertIn('PID 3',report); self.assertNotIn('PRIVATE-KEY',report)
        result = subprocess.CompletedProcess([], 1, b'', b'PRIVATE-KEY')
        with patch.object(d.subprocess,'run',return_value=result): report=d.format_report(d.process_clues(self.plugin))
        self.assertNotIn('PRIVATE-KEY',report)

    @unittest.skipUnless(os.name=='nt', 'Windows EXE')
    def test_shipped_exe_readonly_fixed_and_old_cases(self):
        exe=os.getenv('AAA_QUICK_DOCTOR_EXE')
        if not exe: self.skipTest('Set AAA_QUICK_DOCTOR_EXE to validate the packaged executable')
        for raw,expected in ((FIXED,0), (("def apply_lora_plan():\n raise ValueError("+repr(d.OLD_ERROR)+")\n").encode(),1)):
            put(self.plugin/'preset_runtime.py',raw)
            before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            result=subprocess.run([exe,'--check',str(self.plugin)],timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode,expected)
            self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})


if __name__=='__main__': unittest.main()
