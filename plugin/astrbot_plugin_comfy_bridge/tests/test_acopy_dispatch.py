import ast
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from astrbot_plugin_comfy_bridge.replay_runtime import copy_context
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class CopyDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_quote_skips_reverse_and_explicit_options_win(self):
        await self._run_case('make rain')

    async def test_role_only_quote_needs_no_llm_or_reverse(self):
        await self._run_case('')

    async def _run_case(self, instruction):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ComfyWorkflowBridge')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='acopy')
        method.decorator_list=[]
        class Reply: pass
        ns=dict(globals(),AstrMessageEvent=object,Comp=SimpleNamespace(Reply=Reply),
            current_text_provider_id=AsyncMock(return_value='provider'),
            parse_generation_directives=lambda text: (instruction, {'character':'new'}),
            compile_prompt=lambda text,path,**kwargs: text)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'acopy','exec'),ns)
        parent={'input':{'prompt':'sitting'},'model':{'character_name':'old','style_name':'ink'},'sampling':{'steps':30}}
        bridge=SimpleNamespace(
            _parse_reverse_body=lambda body: (instruction, {'style':'当前画风'}, 'full', (), False),
            _safety_input=AsyncMock(),config={},
            _quoted_job=AsyncMock(return_value=(parent,0)),
            _image_resolver=SimpleNamespace(resolve=AsyncMock()),
            _run_reverse_workflow=AsyncMock(),
            _character_dictionary_path=lambda: Path('unused'),
            _llm_max_tokens=lambda: 700,
            context=SimpleNamespace(llm_generate=AsyncMock(return_value=SimpleNamespace(completion_text='{"prompt":"rain, sitting"}'))),
            _deliver_generation=AsyncMock())
        event=SimpleNamespace(should_call_llm=lambda value:None,stop_event=lambda:None,
            get_messages=lambda:[Reply()], send=AsyncMock(),plain_result=lambda text:text)
        await ns['acopy'](bridge,event,'角色=new ' + instruction)
        if not instruction:
            ns['current_text_provider_id'].assert_not_awaited()
            bridge.context.llm_generate.assert_not_awaited()
        bridge._image_resolver.resolve.assert_not_awaited()
        bridge._run_reverse_workflow.assert_not_awaited()
        args=bridge._deliver_generation.await_args.kwargs
        self.assertEqual(args['options']['character'],'new')
        self.assertEqual(args['options']['style'],'ink')
        self.assertEqual(args['options']['steps'],30)
