"""QQ Official receipts; no QQ account/network/GPU is used by these tests."""
import ast
import copy
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, Mock

from test_delivery_tracking import DeliveryTests
from astrbot_plugin_comfy_bridge.delivery_runtime import (
    send_tracked_image, send_tracked_text, delivery_scope, qq_official_reply_ids,
    log_qq_official_quote_diagnostic,
    qq_official_quote_markers,
)
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.workflow_runtime import extract_command_body
from astrbot_plugin_comfy_bridge.replay_runtime import replay_workflow
from astrbot_plugin_comfy_bridge.safety_runtime import positive_texts


class OfficialEvent:
    """4.27.2 contract: send() discards _post_send() return value."""
    def __init__(self, response=None, group=False):
        self.message_obj = SimpleNamespace(self_id='qq_official' if group else 'unknown_selfid', raw_message=None)
        self.unified_msg_origin = 'official-instance:' + ('GroupMessage:group-a' if group else 'FriendMessage:user-a')
        self.platform_id = 'official-instance'
        self.get_platform_id = lambda: self.platform_id
        self.get_platform_name = lambda: 'qq_official'
        self.get_group_id = lambda: 'group-a' if group else ''
        self.get_sender_id = lambda: 'user-a'
        self.send_buffer = None
        self.post_send_one = AsyncMock(return_value=response)
        self.public_sends = 0
        self.components = []

    def image_result(self, path): return SimpleNamespace(chain=[('image', path)])
    def plain_result(self, text): return SimpleNamespace(chain=[('text', text)])
    def get_messages(self): return self.components

    async def send(self, message):
        self.public_sends += 1
        self.send_buffer = message
        await self._post_send()

    async def _post_send(self, stream=None):
        if not self.send_buffer: return None
        result = await self.post_send_one(self.send_buffer)
        self.send_buffer = None
        return result


class OfficialDeliveryTests(DeliveryTests):
    def quoted_method(self):
        source = Path(__file__).resolve().parents[1]/'main.py'
        tree = ast.parse(source.read_text('utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='ComfyWorkflowBridge')
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='_quoted_job')
        class Reply:
            def __init__(self, ident): self.id=ident
        scope = dict(globals(), Comp=SimpleNamespace(Reply=Reply), re=__import__('re'), time=__import__('time'), logger=Mock())
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'qq_official_quote', 'exec'), scope)
        resolver=SimpleNamespace(_raw_segments=lambda event: [], resolve=AsyncMock(return_value=None))
        owner=SimpleNamespace(_job_store=lambda:self.store, _image_resolver=resolver, _event_source=lambda event:self.source)
        return MethodType(scope['_quoted_job'], owner), resolver, Reply

    async def test_official_c2c_receipt_and_caption_sent_once(self):
        event=OfficialEvent({'id':'official-result-A'})
        before=self.path.read_bytes()
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock(),caption='test caption')
        self.assertEqual(event.public_sends,0)
        event.post_send_one.assert_awaited_once()
        chain=event.post_send_one.await_args.args[0].chain
        self.assertRegex(chain[0][1],r'^AAA-REF:[0-9a-f]{32}\n$')
        self.assertEqual(chain[1:],[('text','test caption'),('image',str(self.path))])
        job,index=self.store.parent_for_message('official-result-A',delivery_scope(event))
        self.assertEqual((job['job_id'],index),(self.job['job_id'],0))
        self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(event.send_buffer)

    async def test_group_object_receipt_and_placeholder_self_id_change(self):
        event=OfficialEvent(SimpleNamespace(id='group-result'),group=True)
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        event.message_obj.self_id='actual-bot-mention-id'
        self.assertIsNotNone(self.store.parent_for_message('group-result',delivery_scope(event)))

    async def test_nested_receipt_for_style_text(self):
        event=OfficialEvent({'data':{'id':'text-result'}})
        await send_tracked_text(event,'style text',self.store,self.job['job_id'],0,Mock())
        self.assertIsNotNone(self.store.parent_for_message('text-result',delivery_scope(event)))
        event.post_send_one.assert_awaited_once()

    async def test_quote_uses_receipt_and_never_downloads_compressed_image(self):
        event=OfficialEvent({'id':'result-A'})
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('result-A')]
        job,index=await method(event)
        self.assertEqual((job['job_id'],index),(self.job['job_id'],0))
        resolver.resolve.assert_not_awaited()

    async def test_quote_raw_reference_dict_or_sdk_object(self):
        for reference in ({'message_reference':{'message_id':'result-A'}}, SimpleNamespace(message_reference=SimpleNamespace(message_id='result-A')),
                          {'message_type':103,'msg_elements':[{'id':'result-A'}]},
                          SimpleNamespace(message_type=103,msg_elements=[SimpleNamespace(message_id='result-A')])):
            event=OfficialEvent({'id':'result-A'})
            await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
            event.message_obj.raw_message=reference
            method,resolver,_=self.quoted_method()
            job,index=await method(event)
            self.assertEqual(job['job_id'],self.job['job_id'])
            self.assertEqual(index,0); resolver.resolve.assert_not_awaited()

    async def test_multiple_quote_ids_refused(self):
        event=OfficialEvent({'id':'result-A'})
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('result-A')]
        event.message_obj.raw_message={'message_reference':{'message_id':'different'}}
        with self.assertRaisesRegex(WorkflowError,'只引用一条'): await method(event)
        resolver.resolve.assert_not_awaited()

    async def test_other_group_or_platform_instance_cannot_read_mapping(self):
        event=OfficialEvent({'id':'result-A'},group=True)
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        for changes in ({'unified_msg_origin':'official-instance:GroupMessage:group-b'}, {'platform_id':'other-instance'}):
            other=OfficialEvent(group=True)
            for key,value in changes.items(): setattr(other,key,value)
            self.assertIsNone(self.store.parent_for_message('result-A',delivery_scope(other)))

    async def test_missing_receipt_does_not_guess_incoming_id_or_resend(self):
        event=OfficialEvent(None); event.message_obj.message_id='incoming-not-result'
        logger=Mock()
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,logger)
        self.assertEqual(event.public_sends,0); event.post_send_one.assert_awaited_once()
        self.assertFalse((self.store.root/'deliveries').exists())
        logger.warning.assert_called_once()

    async def test_send_error_does_not_retry_and_clears_own_buffer(self):
        event=OfficialEvent(); event.post_send_one.side_effect=TimeoutError('uncertain send')
        with self.assertRaises(TimeoutError):
            await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        event.post_send_one.assert_awaited_once(); self.assertEqual(event.public_sends,0)
        self.assertIsNone(event.send_buffer)
        self.assertFalse((self.store.root/'deliveries').exists())

    async def test_existing_buffer_is_not_overwritten(self):
        event=OfficialEvent(); pending=event.plain_result('pending'); event.send_buffer=pending
        with self.assertRaisesRegex(RuntimeError,'缓冲'):
            await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        self.assertIs(event.send_buffer,pending); event.post_send_one.assert_not_awaited()

    async def test_other_version_public_send_receipt_supported_once(self):
        event=OfficialEvent(); event._post_send=None
        event.send=AsyncMock(return_value={'id':'public-receipt'})
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        event.send.assert_awaited_once()
        self.assertIsNotNone(self.store.parent_for_message('public-receipt',delivery_scope(event)))

    async def test_duplicate_pixels_keep_exact_index_and_job(self):
        second=self.store.register_asset(self.path,asset_type='result',job_id=self.job['job_id'],source='test')
        self.job['result']['assets'].append(second['asset_id']); self.store.save_job(self.job)
        event=OfficialEvent({'id':'second-result'})
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],1,Mock())
        job,index=self.store.parent_for_message('second-result',delivery_scope(event))
        self.assertEqual(job['job_id'],self.job['job_id']); self.assertEqual(index,1)

    async def test_aremake_replays_snapshot_then_new_result_is_quotable(self):
        await self.check_replay()

    async def test_missing_id_quote_replays_snapshot_and_child_marker_is_quotable(self):
        await self.check_replay(missing_id=True)

    async def check_replay(self, missing_id=False):
        @asynccontextmanager
        async def session(**kwargs): yield object()
        from PIL import Image
        output=self.root/'replayed.png'; Image.new('RGB',(8,8),'blue').save(output)
        self.job['sampling']={'seed':123,'steps':30,'cfg':6.0}
        self.job['input']={'compiled_prompt':'original scenery'}
        self.job['workflow_snapshot']={
            '11':{'class_type':'CLIPTextEncode','inputs':{'text':'original scenery'}},
            '19':{'class_type':'KSampler','inputs':{'seed':123,'steps':30,'cfg':6.0}}}
        self.store.save_job(self.job)
        before=copy.deepcopy(self.job)
        event=OfficialEvent()
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('original-image')]
        event.message_str='/aremake 固定种子'; event.should_call_llm=Mock(); event.stop_event=Mock()
        event.post_send_one.side_effect=[{'id':'status-message'}, {'id':'completion-message'}, {'id':'new-image'}]
        self.store.record_delivery('original-image',delivery_scope(event),self.job['job_id'],0)
        if missing_id:
            marker='a'*32
            self.store.record_delivery('qqref:'+marker,delivery_scope(event),self.job['job_id'],0)
            event.components=[Reply('')]
            event.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':'AAA-REF:'+marker,'attachments':[{'url':'compressed-platform-image'}]}]}
        bridge=SimpleNamespace(config={},_job_store=lambda:self.store,_event_source=lambda event:self.source,
            _image_resolver=resolver,_safety_guard=Mock(),_safety_policy=lambda event=None:SimpleNamespace(fingerprint='same'),
            _safety_input=AsyncMock(),_safety_applies=lambda event:False,_safety_outputs=AsyncMock(side_effect=lambda event,paths:paths),
            _generation_slot=lambda event:session(),_timeout_seconds=lambda:5,_character_dictionary_path=lambda:self.root/'dictionary.json',
            _submit_workflow=AsyncMock(return_value='comfy-id'),_wait_for_history=AsyncMock(return_value={}),
            _download_images=AsyncMock(return_value=[output]))
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text('utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ComfyWorkflowBridge')
        methods=[n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name in {'aremake','_quoted_job'}]
        for n in methods: n.decorator_list=[]
        logger=Mock()
        ns=dict(globals(),__package__='astrbot_plugin_comfy_bridge',AstrMessageEvent=object,
                Comp=SimpleNamespace(Reply=Reply),logger=logger,
                aiohttp=SimpleNamespace(ClientSession=session,ClientTimeout=lambda **kw:kw),
                extract_output_images=lambda record:[{'filename':'replayed.png'}])
        exec(compile(ast.Module(body=methods,type_ignores=[]),'official_replay','exec'),ns)
        bridge._quoted_job=MethodType(ns['_quoted_job'],bridge)
        await ns['aremake'](bridge,event,'固定种子')
        logger.exception.assert_not_called()
        graph=bridge._submit_workflow.await_args.args[1]
        self.assertEqual(graph,self.job['workflow_snapshot'])
        self.assertEqual(self.store.get_job(self.job['job_id']),before)
        event.components=[Reply('new-image')]
        if missing_id:
            child_chain=event.post_send_one.await_args.args[0].chain
            event.components=[Reply('')]
            event.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':child_chain[0][1]}]}
        job,index=await bridge._quoted_job(event)
        self.assertNotEqual(job['job_id'],self.job['job_id'])
        self.assertEqual(job['parent_job_id'],self.job['job_id'])
        self.assertEqual(job['status'],'completed'); self.assertEqual(index,0)
        self.assertEqual(job['input']['compiled_prompt'],'original scenery')
        self.assertEqual(job['sampling']['seed'],123)
        self.assertIsNone(self.store.parent_for_message('status-message',delivery_scope(event)))
        self.assertIsNone(self.store.parent_for_message('completion-message',delivery_scope(event)))
        resolver.resolve.assert_not_awaited()

    async def test_marker_missing_native_id_restores_exact_job_after_store_reload(self):
        event=OfficialEvent({'id':'receipt'},group=True)
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        sent_text=event.post_send_one.await_args.args[0].chain[0][1]
        self.store=type(self.store)(self.store.root)
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('')]
        event.message_obj.raw_message=SimpleNamespace(message_type=103,msg_elements=[{'content':sent_text,'attachments':[{'url':'compressed-image'}]}])
        job,index=await method(event)
        self.assertEqual((job['job_id'],index),(self.job['job_id'],0))
        resolver.resolve.assert_not_awaited()

    def test_marker_only_reads_quoted_content_not_current_message(self):
        marker='AAA-REF:'+'a'*32
        event=OfficialEvent()
        event.message_str=marker
        event.message_obj.raw_message={'content':marker,'message_type':0,'msg_elements':[{'content':marker}]}
        self.assertEqual(qq_official_quote_markers(event),set())
        event.message_obj.raw_message=SimpleNamespace(raw_data={'message_type':103,'msg_elements':[{'content':marker}]})
        self.assertEqual(qq_official_quote_markers(event),{'qqref:'+'a'*32})
        event.message_obj.raw_message=None
        self.assertEqual(qq_official_quote_markers(event,[SimpleNamespace(message_str=marker,text=marker)]),{'qqref:'+'a'*32})

    async def test_marker_wrong_group_or_instance_and_unknown_nonce_fail_closed(self):
        event=OfficialEvent({'id':'receipt'},group=True)
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        sent_text=event.post_send_one.await_args.args[0].chain[0][1]
        for changes, content in (({'unified_msg_origin':'other:GroupMessage:other'},sent_text),
                                 ({'platform_id':'other'},sent_text),({},'AAA-REF:'+'0'*32)):
            other=OfficialEvent(group=True)
            for key,value in changes.items(): setattr(other,key,value)
            other.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':content}]}
            method,resolver,Reply=self.quoted_method()
            other.components=[Reply('')]
            with self.assertRaisesRegex(WorkflowError,'引用标记未关联'): await method(other)
            resolver.resolve.assert_not_awaited()

    async def test_multiple_markers_and_conflicting_real_id_refused(self):
        event=OfficialEvent({'id':'receipt'})
        await send_tracked_image(event,self.path,self.store,self.job['job_id'],0,Mock())
        text=event.post_send_one.await_args.args[0].chain[0][1]
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('receipt')]
        event.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':text+'AAA-REF:'+'0'*32}]}
        with self.assertRaisesRegex(WorkflowError,'只引用一条'): await method(event)
        second=self.store.create_job(workflow_type='test',workflow_version='1',profile='',source=self.source,input_data={})
        second['result']['assets']=[self.asset['asset_id']]; self.store.save_job(second)
        self.store.record_delivery('other-receipt',delivery_scope(event),second['job_id'],0)
        event.components=[Reply('other-receipt')]
        event.message_obj.raw_message['msg_elements'][0]['content']=text
        with self.assertRaisesRegex(WorkflowError,'关联冲突'): await method(event)
        resolver.resolve.assert_not_awaited()

    async def test_missing_id_old_unmarked_quote_gives_clear_error_without_download(self):
        event=OfficialEvent()
        method,resolver,Reply=self.quoted_method()
        event.components=[Reply('')]
        event.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':'old unmarked image'}]}
        with self.assertRaisesRegex(WorkflowError,'没有 AAA-REF 标记'): await method(event)
        resolver.resolve.assert_not_awaited()

    async def test_per_image_marker_selects_exact_index_in_same_job(self):
        second=self.store.register_asset(self.path,asset_type='result',job_id=self.job['job_id'],source='test')
        self.job['result']['assets'].append(second['asset_id']); self.store.save_job(self.job)
        event=OfficialEvent({'id':'receipt'})
        texts=[]
        for index in (0,1):
            event.post_send_one.return_value={'id':'receipt-'+str(index)}
            await send_tracked_image(event,self.path,self.store,self.job['job_id'],index,Mock())
            texts.append(event.post_send_one.await_args.args[0].chain[0][1])
        self.assertNotEqual(texts[0],texts[1])
        method,resolver,Reply=self.quoted_method()
        for index,text in enumerate(texts):
            event.components=[Reply('')]
            event.message_obj.raw_message={'message_type':103,'msg_elements':[{'content':text}]}
            job,result_index=await method(event)
            self.assertEqual((job['job_id'],result_index),(self.job['job_id'],index))
        resolver.resolve.assert_not_awaited()

    def test_current_message_id_is_never_a_quote(self):
        event=OfficialEvent(); event.message_obj.raw_message={'id':'incoming','message_id':'incoming'}
        self.assertEqual(qq_official_reply_ids(event),set())

    def diagnostic(self, event, ids):
        logger=Mock()
        log_qq_official_quote_diagnostic(event,ids,self.store,logger)
        return json.loads(logger.info.call_args.args[1])

    def test_diagnostic_exact_match_is_read_only_and_redacted(self):
        event=OfficialEvent(group=True)
        self.store.record_delivery('private-receipt',delivery_scope(event),self.job['job_id'],0)
        before={path:path.read_bytes() for path in self.store.root.rglob('*') if path.is_file()}
        report=self.diagnostic(event,{'private-receipt'})
        self.assertEqual(report['exact_matches'],1)
        self.assertNotIn('private-receipt',json.dumps(report))
        self.assertNotIn(event.unified_msg_origin,json.dumps(report))
        self.assertEqual(before,{path:path.read_bytes() for path in self.store.root.rglob('*') if path.is_file()})

    def test_diagnostic_distinguishes_scope_mismatch(self):
        event=OfficialEvent(group=True)
        self.store.record_delivery('receipt',delivery_scope(event),self.job['job_id'],0)
        event.unified_msg_origin='other-instance:GroupMessage:other-group'
        report=self.diagnostic(event,{'receipt'})
        self.assertEqual((report['id_matches'],report['scope_matches'],report['exact_matches']),(1,0,0))

    def test_diagnostic_distinguishes_id_mismatch_and_absent_ids(self):
        event=OfficialEvent(group=True)
        self.store.record_delivery('saved',delivery_scope(event),self.job['job_id'],0)
        for ids in ({'different'},set()):
            report=self.diagnostic(event,ids)
            self.assertEqual((report['id_matches'],report['scope_matches'],report['exact_matches']),(0,1,0))
            self.assertEqual(len(report['quote_ids']),len(ids))

    def test_diagnostic_raw_payload_shape_does_not_log_contents_or_urls(self):
        event=OfficialEvent()
        event.message_obj.raw_message=SimpleNamespace(raw_data={
            'message_reference':{'message_id':'raw-only-id'},
            'msg_elements':[{'content':'sensitive prompt','attachments':[{'url':'https://private.invalid/token'}]}]})
        report=self.diagnostic(event,set())
        self.assertTrue(report['raw_shape']['payload']['reference_id_present'])
        for value in ('raw-only-id','sensitive prompt','private.invalid','token'):
            self.assertNotIn(value,json.dumps(report))

    def test_diagnostic_corrupt_record_and_logger_failure_cannot_break_quote(self):
        directory=self.store.root/'deliveries'; directory.mkdir(exist_ok=True)
        (directory/'bad.json').write_text('broken',encoding='utf-8')
        self.assertEqual(self.diagnostic(OfficialEvent(),set())['record_errors'],1)
        logger=Mock(); logger.info.side_effect=RuntimeError('logging unavailable')
        log_qq_official_quote_diagnostic(OfficialEvent(),set(),self.store,logger)

    def test_diagnostic_never_runs_for_onebot(self):
        event=OfficialEvent(); event.get_platform_name=lambda:'aiocqhttp'
        logger=Mock()
        log_qq_official_quote_diagnostic(event,{'receipt'},self.store,logger)
        logger.info.assert_not_called()
