import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.remote_jobs import RemoteJobManager, RemoteJobError
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest
from astr_auto_anima_hub.safety_runtime import CreditStore, load_policy


class HubSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        (root/"safety").mkdir()
        (root/"safety/policy.json").write_text(json.dumps({"safety_mode_enabled":True,"safety_review_scope":"both"}))
        target=root/"targets.json"
        target.write_text(json.dumps({"targets":[{"id":"private","label":"test","kind":"private","umo":"qq:FriendMessage:999999","allow_safety":["N","H","S"]}]}))
        self.settings=Settings(plugin_data_dir=root,delivery_targets_override=target,astrbot_api_key="test")
        self.principal=AuthPrincipal(role="user",subject="qq-123456",qq="123456")
        self.image=b"\x89PNG\r\n\x1a\nimage"
        def handler(request):
            if request.url.path=="/api/v1/chat":
                self.username=json.loads(request.content)["username"]
                lines=[{"type":"plain","data":"好图 1/5 完成"},
                       {"type":"attachment_saved","data":{"id":"image1","type":"image"}},
                       {"type":"plain","data":"五连抽结束：成功1/5。"}]
                return httpx.Response(200,text="".join("data: "+json.dumps(x)+"\n\n" for x in lines))
            if request.url.path=="/api/v1/file":
                return httpx.Response(200,content=self.image,headers={"content-type":"image/png"})
            return httpx.Response(404)
        self.manager=RemoteJobManager(self.settings,transport=httpx.MockTransport(handler))
        self.manager._send_im=AsyncMock()

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.temp.cleanup()

    async def test_stream_approved_identity_and_once_delivery(self):
        store=CreditStore(self.settings.plugin_data_dir/"safety")
        store.approve(self.image,load_policy(self.settings.plugin_data_dir/"safety").fingerprint)
        job=self.manager.create(RemoteJobCreateRequest(target_id="self-private",kind="direct",prompt="solo"),self.principal)
        await asyncio.gather(*tuple(self.manager._tasks))
        result=self.manager.get(job.id,self.principal)
        self.assertEqual(result.status,"succeeded")
        self.assertEqual(len(result.images),1)
        self.assertTrue(self.username.startswith("aaa_safe_"))
        self.assertEqual(self.manager._send_im.await_count,1)
        ticket=json.loads(next((self.settings.plugin_data_dir/"safety/tickets").glob("*.json")).read_text())
        self.assertEqual(ticket["qq"],"123456")
        self.assertFalse(ticket["admin_exempt"])

    async def test_unapproved_never_published_or_delivered(self):
        job=self.manager.create(RemoteJobCreateRequest(target_id="self-private",kind="direct",prompt="solo"),self.principal)
        await asyncio.gather(*tuple(self.manager._tasks))
        result=self.manager.get(job.id,self.principal)
        self.assertEqual(result.status,"failed")
        self.assertFalse(result.images)
        self.manager._send_im.assert_not_awaited()

    async def test_zero_and_missing_qq_rejected_before_queue(self):
        payload=RemoteJobCreateRequest(target_id="self-private",kind="direct",prompt="solo")
        with self.assertRaises(RemoteJobError):
            self.manager.create(payload,AuthPrincipal(role="user",subject="unbound"))
        store=CreditStore(self.settings.plugin_data_dir/"safety")
        for i in range(10):
            store.block(str(i),"123456","input",[])
        with self.assertRaises(RemoteJobError):
            self.manager.create(payload,self.principal)
        self.assertFalse(self.manager._tasks)

    async def test_admin_no_qq_can_generate_without_global_approval(self):
        admin = AuthPrincipal(role="admin", subject="admin")
        payload = RemoteJobCreateRequest(target_id="private", kind="direct", prompt="nude")
        job = self.manager.create(payload, admin)
        await asyncio.gather(*tuple(self.manager._tasks))
        result = self.manager.get(job.id, admin)
        self.assertEqual(result.status, "succeeded", result.message)
        self.assertEqual(len(result.images), 1)
        self.assertIsNotNone(self.manager.get_image(job.id, result.images[0].id, admin))
        self.assertIsNone(self.manager.get_image(job.id, result.images[0].id, self.principal))
        ticket = json.loads(next((self.settings.plugin_data_dir/"safety/tickets").glob("*.json")).read_text())
        self.assertTrue(ticket["admin_exempt"])
        with self.assertRaises(RemoteJobError):
            self.manager._require_approved(self.image)
        reloaded = RemoteJobManager(self.settings)
        try:
            self.assertIsNotNone(reloaded.get_image(job.id, result.images[0].id, admin))
        finally:
            await reloaded.shutdown()

    async def test_user_cannot_self_report_admin_exemption(self):
        payload = RemoteJobCreateRequest.model_validate({"target_id": "self-private", "kind": "direct", "prompt": "solo", "admin_exempt": True})
        job = self.manager.create(payload, self.principal)
        await asyncio.gather(*tuple(self.manager._tasks))
        self.assertNotIn(job.id, self.manager._admin_exempt_jobs)
        self.assertEqual(self.manager.get(job.id, self.principal).status, "failed")


if __name__ == "__main__":
    unittest.main()
