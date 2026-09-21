from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from astrbot.api.event import MessageChain

from .safety_runtime import Policy, CreditStore, PriorityGate, match_rules, validate_audit, RANDOM_REVIEW
from .workflow_runtime import WorkflowError


class SafetyBridge:
    def _safety_admin_exempt(self, event):
        if event is None:
            return False
        origin = str(event.unified_msg_origin or "")
        if "webchat" in origin.casefold():
            # AstrBot's webchat role can be shared by many Hub users. Only the
            # server-written, expiring per-job ticket may grant exemption.
            match = re.search(r"(?:^|_)aaa_safe_([a-f0-9]{32})$", str(event.get_sender_id()))
            root = getattr(self, "_safety_root_dir", None)
            if not match or root is None:
                return False
            path = root / "tickets" / f"{match[1]}.json"
            try:
                if path.is_symlink() or not path.is_file():
                    return False
                data = json.loads(path.read_text(encoding="utf-8"))
                return (data.get("admin_exempt") is True
                        and bool(data.get("root"))
                        and float(data.get("expires", 0)) > time.time())
            except (OSError, ValueError, TypeError):
                return False
        checker = getattr(event, "is_admin", None)
        try:
            return callable(checker) and checker() is True
        except Exception:
            return False

    def _safety_applies(self, event):
        return self._safety_policy().enabled and not self._safety_admin_exempt(event)

    def _safety_setup(self, concurrency):
        self._safety_root_dir = self._character_dictionary_path().parent / "safety"
        self._safety_store = CreditStore(self._safety_root_dir)
        self._safety_gate = PriorityGate(concurrency)
        self._safety_rules = json.loads((Path(__file__).parent / "data/safety_rules.json").read_text(encoding="utf-8"))["rules"]
        self._safety_policy_signature = None
        self._safety_policy()

    def _safety_policy(self):
        if not hasattr(self, "_safety_root_dir"):
            if not self.config.get("safety_mode_enabled", False):
                return Policy({})
            self._safety_setup(max(1, int(self.config.get("max_concurrency", 1))))
        policy = Policy(self.config)
        data = {key: self.config.get(key, default) for key, default in [
            ("safety_mode_enabled", False), ("safety_review_scope", "both"),
            ("safety_exempt_terms", ""), ("safety_admin_qq", "")
            , ("safety_audit_threshold", 0.35)
        ]}
        signature = json.dumps(data, sort_keys=True)
        if signature != self._safety_policy_signature:
            path = self._safety_root_dir / "policy.json"
            temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temp.write_text(signature, encoding="utf-8")
            temp.replace(path)
            self._safety_policy_signature = signature
        return policy

    def _safety_identity(self, event):
        if event is None:
            raise WorkflowError("安全模式无法确认发起者 QQ，生成失败")
        sender = str(event.get_sender_id())
        origin = str(event.unified_msg_origin or "")
        ticket_match = re.search(r"(?:^|_)aaa_safe_([a-f0-9]{32})$", sender)
        if ticket_match and "webchat" in origin.casefold():
            ticket = self._safety_root_dir / "tickets" / f"{ticket_match[1]}.json"
            if not ticket.is_file() or ticket.is_symlink():
                raise WorkflowError("安全身份凭据无效，生成失败")
            data = json.loads(ticket.read_text(encoding="utf-8"))
            if float(data.get("expires", 0)) < time.time():
                raise WorkflowError("安全身份凭据过期，生成失败")
            qq, root = str(data.get("qq", "")), str(data.get("root", ""))
        else:
            if "webchat" in origin.casefold():
                raise WorkflowError("安全模式需要新版 Hub 身份凭据，生成失败")
            qq = sender
            root = getattr(event, "_aaa_safety_root", "")
            if not root:
                message_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
                if message_id in {"", "0", "None"}:
                    message_id = uuid.uuid4().hex
                root = hashlib.sha256(f"{origin}|{sender}|{message_id}".encode()).hexdigest()
                setattr(event, "_aaa_safety_root", root)
        if not re.fullmatch(r"[1-9][0-9]{4,14}", qq) or not root:
            raise WorkflowError("安全模式缺少有效 QQ 绑定，生成失败")
        return qq, root

    def _safety_guard(self, event):
        if self._safety_applies(event):
            targets = [x.strip() for x in str(self.config.get("safety_admin_umos", "")).splitlines() if x.strip()]
            if not targets or any(not re.fullmatch(r"[^:]+:FriendMessage:[1-9][0-9]{4,14}", x) for x in targets):
                raise WorkflowError("请先配置有效的安全信用通知管理员私聊 UMO，生成失败（未扣分）")
            qq, _ = self._safety_identity(event)
            if self._safety_store.score(qq) <= 0:
                raise WorkflowError("安全模式信用为 0，生成失败；请联系管理员")

    def _safety_priority(self, event):
        if not self._safety_applies(event):
            return 0
        try:
            qq, _ = self._safety_identity(event)
            return int(self._safety_store.score(qq) < 5)
        except Exception:
            return 1

    @asynccontextmanager
    async def _generation_slot(self, event):
        from .idle_guard_runtime import admission
        try:
            lease = admission(self._character_dictionary_path().parent)
        except RuntimeError as exc:
            raise WorkflowError(str(exc)) from exc
        try:
            async with self._generation_slot_unlocked(event):
                yield
        finally:
            if lease:
                lease.close()

    @asynccontextmanager
    async def _generation_slot_unlocked(self, event):
        self._safety_guard(event)
        if not hasattr(self, "_safety_gate"):
            async with self._semaphore:
                yield
            return
        async with self._safety_gate.slot(lambda: self._safety_priority(event)):
            self._safety_guard(event)
            yield

    async def _safety_notice_loop(self):
        while True:
            try:
                if self._safety_policy().enabled:
                    await self._safety_notices()
            except Exception:
                pass  # Durable outbox is retained for the next attempt.
            await asyncio.sleep(30)

    async def _safety_notices(self):
        targets = [x.strip() for x in str(self.config.get("safety_admin_umos", "")).splitlines() if x.strip()]
        with self._safety_store.connect() as db:
            notices = db.execute("SELECT id,qq,credit,root FROM notices WHERE sent=0").fetchall()
        for notice, qq, score, root in notices:
            sent = bool(targets)
            for target in targets:
                if not re.fullmatch(r"[^:]+:FriendMessage:[1-9][0-9]{4,14}", target):
                    sent = False
                    continue
                try:
                    ok = await self.context.send_message(target, MessageChain().message(
                        f"AAA 安全信用提醒：QQ={qq}，信用={score}，{'已禁止生图' if score == 0 else '排队优先级降低一级'}，任务={root}"))
                    if ok is False:
                        sent = False
                except Exception:
                    sent = False
            if sent:
                with self._safety_store.connect() as db:
                    db.execute("UPDATE notices SET sent=1 WHERE id=?", (notice,))

    async def _safety_reject(self, event, stage, hits):
        qq, root = self._safety_identity(event)
        deduct = stage == "selection" or not RANDOM_REVIEW.get()
        score = self._safety_store.block(root, qq, stage, hits, deduct=deduct)
        await self._safety_notices()
        note = "同次任务最多扣1分" if deduct else "非S组抽卡，本次不扣分"
        raise WorkflowError(f"安全审核不予生成，信用={score}（{note}）")

    async def _deliver_random_generation(self, event, **kwargs):
        # Server-owned task context, never a client-provided option; restored on
        # success, rejection, cancellation and exceptions, isolated per task.
        token = RANDOM_REVIEW.set(True)
        try:
            return await self._deliver_generation(event, **kwargs)
        finally:
            RANDOM_REVIEW.reset(token)

    async def _safety_input(self, event, text):
        if not self._safety_applies(event):
            return
        self._safety_guard(event)
        policy = self._safety_policy()
        if policy.input:
            hits = match_rules(text, self._safety_rules, policy.exemptions)
            if hits:
                await self._safety_reject(event, "input", hits)

    async def _safety_outputs(self, event, paths):
        if not self._safety_applies(event):
            # Do not create a global approval receipt for exempt images.
            return paths
        self._safety_guard(event)
        policy = self._safety_policy()
        if not policy.enabled:
            return paths
        initial_policy = policy.fingerprint
        if policy.output:
            try:
                threshold = float(self.config.get("safety_audit_threshold", 0.35))
                if not 0 < threshold < 1:
                    raise ValueError("invalid threshold")
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=int(self.config.get("safety_audit_timeout", 120)))) as session:
                    for path in paths:
                        workflow = json.loads((Path(__file__).parent / "data/safety_audit_workflow.json").read_text(encoding="utf-8"))
                        nonce = uuid.uuid4().hex
                        workflow["1"]["inputs"]["image"] = await self._upload_reverse_image(session, str(path))
                        workflow["3"]["inputs"]["threshold"] = threshold
                        workflow["3"]["inputs"]["character_threshold"] = threshold
                        workflow["4"]["inputs"]["nonce"] = nonce
                        prompt_id = await self._submit_workflow(session, workflow)
                        record = await asyncio.wait_for(self._wait_for_history(session, prompt_id), timeout=int(self.config.get("safety_audit_timeout", 120)))
                        tags = validate_audit(record, nonce)
                        hits = match_rules(tags, self._safety_rules, policy.exemptions)
                        if hits:
                            hits.append({"quarantine_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                            await self._safety_reject(event, "output", hits)
            except WorkflowError as exc:
                if "安全审核不予生成" in str(exc):
                    raise
                raise WorkflowError("安全审核暂不可用，生成失败（未扣分）") from exc
            except Exception as exc:
                raise WorkflowError("安全审核暂不可用，生成失败（未扣分）") from exc
        if self._safety_policy().fingerprint != initial_policy:
            raise WorkflowError("审核期间安全配置已变化，请重新提交（未扣分）")
        approved = []
        for path in paths:
            content = path.read_bytes()
            self._safety_store.approve(content, initial_policy)
            destination = self._output_dir() / f"approved_{uuid.uuid4().hex}{path.suffix}"
            shutil.copy2(path, destination)
            approved.append(destination)
        return approved
