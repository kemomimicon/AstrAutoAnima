"""Local ComfyUI execution without an AstrBot or messaging-platform hop."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import time
import uuid
from pathlib import Path

import httpx

from .auth import AuthPrincipal, SYSTEM_ADMIN
from .config import Settings
from .local_generation import (LocalGenerationError, SIZES, build_local_workflow,
                               clean_llm_tags, local_preset_snapshot)
from .local_gufeng import draw_gufeng, gufeng_available
from .prompt_favorites import full_prompt
from .remote_jobs import RemoteJobError, RemoteJobManager, _now
from .schemas import DeliveryTarget, DeliveryTargetListResponse, RemakeOptions, RemoteJobCreateRequest, RemoteJobResponse


_TRANSLATION_SYSTEM = (
    "你是 Anima 图像模型的提示词转换器。把用户中文描述忠实转换为一行英文 "
    "Danbooru-style tags，使用英文逗号分隔。保留指定的人数、角色、服装、动作、"
    "表情、构图、环境和光影。不要添加画师、质量词、LoRA 语法或解释；不要输出中文。"
)


class LocalJobManager(RemoteJobManager):
    def _load_persisted_jobs(self) -> None:
        # Called by the parent constructor. Keep local records and media away
        # from Bot-delivered jobs even when both modes use the same data root.
        legacy_records = self._records_dir
        root = self.settings.hub_state_dir / "local_jobs"
        self._records_dir = root / "records"
        self._media_dir = root / "media"
        self._meta_dir = root / "runs"
        for source in (self._records_dir, legacy_records):
            if not source.is_dir():
                continue
            for path in sorted(source.glob("*.json")):
                try:
                    stored = json.loads(path.read_text(encoding="utf-8-sig"))
                    owner = str(stored.get("owner", "")).strip()
                    job = RemoteJobResponse.model_validate(stored.get("job", {}))
                except (OSError, ValueError):
                    continue
                if not owner or path.stem != job.id or job.target_id != "local":
                    continue
                if source == legacy_records and self._record_path(job.id).exists():
                    continue
                self._jobs[job.id] = job
                self._owners[job.id] = owner
                self._admin_exempt_jobs.add(job.id)
                if source == legacy_records:
                    self._persist(job.id)
                if job.status in {"queued", "running"} and not self._meta_path(job.id).is_file():
                    self._update(job.id, status="failed",
                                 message="旧本机任务缺少恢复信息；请检查 ComfyUI 历史")

    def _meta_path(self, job_id: str) -> Path:
        return self._meta_dir / f"{uuid.UUID(hex=job_id).hex}.json"

    def get_image(self, job_id: str, image_id: str,
                  principal: AuthPrincipal = SYSTEM_ADMIN):
        located = super().get_image(job_id, image_id, principal)
        if located is not None:
            return located
        # Preserve images from local jobs written before the record split.
        job = self.get(job_id, principal)
        image = next((item for item in job.images if item.id == image_id), None) if job else None
        if image is None:
            return None
        suffix = Path(image.filename).suffix.casefold()
        path = self.settings.remote_job_store_dir / "media" / job_id / f"{image.id}{suffix}"
        if not path.is_file() or path.is_symlink():
            return None
        self._require_approved(path.read_bytes(), job_id)
        return image, path

    def _read_meta(self, job_id: str) -> dict:
        try:
            return json.loads(self._meta_path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LocalGenerationError("本机任务快照缺失或损坏") from exc

    def _write_meta(self, job_id: str, data: dict) -> None:
        path = self._meta_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    async def resume(self) -> None:
        for job_id, job in list(self._jobs.items()):
            if job.status not in {"queued", "running"}:
                continue
            try:
                meta = self._read_meta(job_id)
                if meta.get("workflow") and not meta.get("prompt_id"):
                    self._update(job_id, status="failed", message=(
                        "Hub 在提交 ComfyUI 时中断，提交结果不明；请检查 ComfyUI 历史，避免重复生成"))
                    continue
                payload = RemoteJobCreateRequest.model_validate(meta["payload"])
            except (KeyError, ValueError, LocalGenerationError):
                self._update(job_id, status="failed", message="本机任务恢复信息无效")
                continue
            task = asyncio.create_task(self._run_local(job_id, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def targets(self, principal: AuthPrincipal = SYSTEM_ADMIN) -> DeliveryTargetListResponse:
        return DeliveryTargetListResponse(targets=[DeliveryTarget(
            id="local", label="本机工作站 · 仅保存记录", kind="private")]
            if principal.is_admin else [])

    def create(self, payload: RemoteJobCreateRequest,
               principal: AuthPrincipal = SYSTEM_ADMIN) -> RemoteJobResponse:
        if not principal.is_admin:
            raise RemoteJobError("本机工作站仅允许本机管理员令牌提交")
        if payload.target_id != "local" or payload.deliver_to_im:
            raise RemoteJobError("本机模式只接受 local 目标且不能投递到消息平台")
        if payload.kind not in {"direct", "chinese", "hq", "random"}:
            raise RemoteJobError("本机模式当前仅支持直接生图、中文生图、HQ 和 V 组单张；其他模式尚未接入")
        if (payload.kind != "random" and not payload.prompt.strip()) or payload.five_draw or payload.task_suite_id:
            raise RemoteJobError("本机直接生图需要提示词；五连抽和任务套组尚未接入")
        if payload.kind == "random":
            from .prompt_catalog import source_policy
            policy = source_policy(self.settings, "V")
            if not policy["enabled"] or not policy["allow_private"]:
                raise RemoteJobError("此词库已停用或不允许本机个人任务")
            payload = payload.model_copy(update={"safety_code": policy["default_safety"]})
            if payload.custom_groups != ["v"] or payload.pool_filter:
                raise RemoteJobError("本机来张好图仅支持 V · 国风古韵单组，不支持来源/分级筛选")
            if not gufeng_available(self.settings.local_gufeng_catalog_path):
                raise RemoteJobError("请先安装并配置 V · 国风古韵离线资源组件")
        if payload.personal_style_slot or payload.trial_style or payload.style == "随机模式":
            raise RemoteJobError("个人画风／临时调色盘／随机画风尚未接入本机执行器")
        if ((payload.kind != "random" and (payload.pool_filter or payload.custom_groups))
                or payload.source_image_data or payload.detail_upscale or any((
            payload.detail_hands, payload.detail_feet, payload.detail_face,
            payload.camera_distance, payload.camera_yaw, payload.camera_pitch,
            payload.camera_lens, payload.camera_roll, payload.camera_extreme_lora,
            payload.lighting_key, payload.lighting_effect, payload.material_primary,
            payload.material_surface, payload.material_details,
        ))):
            raise RemoteJobError("当前本机工作流暂不支持所选高级参数；已拒绝而非静默忽略")
        if self.settings.local_workflow_path is None or not self.settings.local_workflow_path.is_file():
            raise RemoteJobError("请先配置 AAH_LOCAL_WORKFLOW_PATH")
        if payload.kind == "chinese" and not (self.settings.local_llm_base_url and self.settings.local_llm_model):
            raise RemoteJobError("中文生图需要配置 AAH_LOCAL_LLM_BASE_URL 和 AAH_LOCAL_LLM_MODEL")
        now = _now()
        job = RemoteJobResponse(
            id=uuid.uuid4().hex, status="queued", kind=payload.kind,
            # Owner-confirmed SFW normal catalog; existing frozen jobs retain
            # their recorded grade rather than rewriting historical data.
            safety_code=payload.safety_code, profile=payload.profile,
            target_id="local", target_label="本机工作站", deliver_to_im=False,
            command_preview=("来张好图 V · 国风古韵 " + payload.prompt).strip()
                            if payload.kind == "random" else payload.prompt,
            source_prompt=payload.prompt,
            message="已进入本机 ComfyUI 队列", created_at=now, updated_at=now,
        )
        self._jobs[job.id] = job
        self._owners[job.id] = principal.subject
        self._admin_exempt_jobs.add(job.id)
        self._persist(job.id)
        meta = {"payload": payload.model_dump(mode="json")}
        if payload.kind == "random":
            meta["selection_seed"] = secrets.randbelow(2**63 - 1)
            # Existing queued jobs and frozen snapshots keep their original
            # semantics; only newly created draws opt into AAA's prefix.
            meta["v_prefix_policy_version"] = 1
        self._write_meta(job.id, meta)
        task = asyncio.create_task(self._run_local(job.id, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _convert_chinese(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.settings.local_llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.local_llm_api_key}"
        system_prompt = _TRANSLATION_SYSTEM
        guide = self.settings.local_llm_guide_path
        if guide is not None:
            if not guide.is_file() or guide.is_symlink() or guide.stat().st_size > 16_384:
                raise LocalGenerationError("本机转换规则文件不存在、是链接或超过 16 KiB")
            system_prompt += "\n用户自定义术语规则：\n" + guide.read_text(encoding="utf-8-sig")
        async with httpx.AsyncClient(base_url=self.settings.local_llm_base_url.rstrip("/"),
                                     headers=headers, timeout=120,
                                     transport=self._transport) as client:
            response = await client.post("chat/completions", json={
                "model": self.settings.local_llm_model,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": prompt}],
                "temperature": 0.2,
            })
            response.raise_for_status()
            data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalGenerationError("LLM API 返回格式不是 Chat Completions") from exc
        return clean_llm_tags(content)

    async def _run_local(self, job_id: str, payload: RemoteJobCreateRequest) -> None:
        async with self._semaphore:
            self._update(job_id, status="running", message="本机工作站正在准备提示词")
            try:
                meta = self._read_meta(job_id)
                prompt_id = str(meta.get("prompt_id", ""))
                if prompt_id:
                    seed = int(meta["seed"])
                    tags = str(meta["tags"])
                    self._update(job_id, message="正在接回 ComfyUI 已提交任务")
                else:
                    tags = payload.prompt.strip()
                    if payload.kind == "random" and not meta.get("remake_of"):
                        snapshot = meta.get("template_snapshot")
                        if snapshot is None:
                            snapshot = await asyncio.to_thread(
                                draw_gufeng, self.settings.local_gufeng_catalog_path,
                                int(meta["selection_seed"]))
                            if meta.get("v_prefix_policy_version") == 1:
                                snapshot = copy.deepcopy(snapshot)
                                snapshot["catalog_prompt"] = snapshot["prompt"]
                                subject = payload.random_subject_tag or "1girl"
                                prefix = "solo" if subject == "none" else f"{subject}, solo"
                                snapshot["prompt"] = ", ".join(
                                    part for part in (prefix, snapshot["prompt"]) if part)
                                # Keep the applied policy inside the frozen
                                # snapshot so remakes preserve its provenance.
                                snapshot["provenance"].update(
                                    v_prefix_policy_version=1, random_subject_tag=subject)
                            meta["template_snapshot"] = snapshot
                            meta["user_addition"] = payload.prompt.strip()
                            # Freeze before any ComfyUI submission. Restart and
                            # remake do not need to reopen or redraw the catalog.
                            self._write_meta(job_id, meta)
                        tags = full_prompt(snapshot["prompt"], meta.get("user_addition", ""))
                        provenance = {**snapshot["provenance"],
                                      "template_id": snapshot["template_id"],
                                      "scene_zh": snapshot["scene_zh"],
                                      "selection_seed": snapshot["selection_seed"],
                                      "group": "v", "safety_review": "owner_confirmed_sfw",
                                      "collection_safety": self._jobs[job_id].safety_code}
                        self._update(job_id, source_prompt=snapshot["prompt"],
                                     prompt_ids=[snapshot["template_id"]],
                                     prompt_provenance=provenance)
                    if payload.kind == "chinese":
                        tags = await self._convert_chinese(tags)
                        self._update(job_id, converted_prompt=tags,
                                     message="中文转换完成，准备提交 ComfyUI")
                    if meta.get("remake_of"):
                        workflow, seed, final_prompt = await self._prepare_remake(meta, payload)
                        tags = str(meta.get("tags", tags))
                    else:
                        meta["preset_snapshot"] = local_preset_snapshot(self.settings, payload)
                        workflow, seed, final_prompt = build_local_workflow(
                            self.settings, payload, tags, preset_snapshot=meta["preset_snapshot"])
                    self._update(job_id, final_prompt=final_prompt, message="正在提交本机 ComfyUI")
                    meta.update(workflow=workflow, seed=seed, tags=tags,
                                final_prompt=final_prompt)
                    self._write_meta(job_id, meta)
                async with httpx.AsyncClient(base_url=self.settings.comfyui_url.rstrip("/"),
                                             timeout=30, transport=self._transport) as client:
                    if not prompt_id:
                        submitted = await client.post("/prompt", json={"prompt": workflow, "client_id": job_id})
                        submitted.raise_for_status()
                        prompt_id = str(submitted.json().get("prompt_id", ""))
                        if not prompt_id:
                            raise LocalGenerationError("ComfyUI 未返回 prompt_id")
                        meta["prompt_id"] = prompt_id
                        self._write_meta(job_id, meta)
                        self._update(job_id, message=f"ComfyUI 已接收，种子 {seed}")
                    deadline = time.monotonic() + self.settings.remote_job_timeout_seconds
                    record = None
                    while time.monotonic() < deadline:
                        response = await client.get(f"/history/{prompt_id}")
                        response.raise_for_status()
                        record = response.json().get(prompt_id)
                        if isinstance(record, dict):
                            break
                        await asyncio.sleep(1)
                    if not isinstance(record, dict):
                        raise LocalGenerationError("等待 ComfyUI 生成超时；可在 ComfyUI 历史中检查任务")
                    status = record.get("status", {})
                    if isinstance(status, dict) and status.get("status_str") == "error":
                        raise LocalGenerationError("ComfyUI 执行失败；请检查 ComfyUI 日志")
                    images = []
                    outputs = record.get("outputs", {})
                    if not isinstance(outputs, dict):
                        raise LocalGenerationError("ComfyUI 历史记录 outputs 格式无效")
                    for output in outputs.values():
                        if not isinstance(output, dict):
                            continue
                        for item in output.get("images", []):
                            if not isinstance(item, dict) or item.get("type", "output") != "output":
                                continue
                            name = str(item.get("filename", ""))
                            subfolder = str(item.get("subfolder", ""))
                            if not name or Path(name).name != name:
                                raise LocalGenerationError("ComfyUI 返回了非法图片文件名")
                            root = self.settings.output_dir.resolve()
                            path = (root / subfolder / name).resolve()
                            if root not in path.parents or not path.is_file() or path.is_symlink():
                                raise LocalGenerationError("ComfyUI 输出图片不在已配置 output 内")
                            if path.stat().st_size > 64 * 1024 * 1024:
                                raise LocalGenerationError("ComfyUI 输出图片超过 64 MiB 限制")
                            stored = self._store_media_bytes(job_id, path.read_bytes(), name,
                                                             "image/png", source_path=path)
                            if stored is None:
                                raise LocalGenerationError("无法保存 ComfyUI 生成图片")
                            stored.source_prompt = tags
                            stored.final_prompt = str(meta.get('final_prompt', ''))
                            stored.prompt_stage = '当次实际正向提示词'
                            if meta.get("template_snapshot"):
                                snapshot = meta["template_snapshot"]
                                stored.prompt_id = snapshot["template_id"]
                                stored.source_prompt = snapshot["prompt"]
                                stored.user_addition = meta.get("user_addition", "")
                                stored.source_safety_code = self._jobs[job_id].safety_code
                            images.append(stored)
                    if not images:
                        raise LocalGenerationError("ComfyUI 任务结束但没有输出图片")
                    self._update(job_id, status="succeeded", images=images,
                                 message=f"本机生成完成，共 {len(images)} 张；种子 {seed}")
            except asyncio.CancelledError:
                self._update(job_id, message="Hub 已停止；下次启动将检查 ComfyUI 任务")
                raise
            except (LocalGenerationError, httpx.HTTPError, OSError, ValueError, KeyError) as exc:
                self._update(job_id, status="failed", message=str(exc)[:500])
            except Exception as exc:
                self._update(job_id, status="failed",
                             message=f"本机执行器异常：{type(exc).__name__}；请检查 Hub 日志")

    async def _prepare_remake(self, meta: dict, payload: RemoteJobCreateRequest):
        source = meta["remake_of"]
        original = self._read_meta(source)
        options = RemakeOptions.model_validate(meta["remake_options"])
        tags = str(original.get("tags", ""))
        if options.adjustment.strip():
            addition = options.adjustment.strip()
            if any(ord(char) > 127 for char in addition):
                if not (self.settings.local_llm_base_url and self.settings.local_llm_model):
                    raise LocalGenerationError("中文调整内容需要配置本机 LLM API")
                addition = await self._convert_chinese(addition)
            if original.get("template_snapshot"):
                meta["user_addition"] = ", ".join(part for part in (
                    original.get("user_addition", ""), addition) if part)
                tags = full_prompt(original["template_snapshot"]["prompt"], meta["user_addition"])
            else:
                tags = ", ".join(part for part in (tags, addition) if part)
        if options.character or options.style:
            presets = copy.deepcopy(original.get("preset_snapshot", {}))
            original_payload = original["payload"]
            for kind in ("style", "character"):
                if getattr(options, kind):
                    selection = payload.model_copy(update=(
                        {"character": "", "character_variant": ""} if kind == "style" else {"style": ""}))
                    presets[kind] = local_preset_snapshot(self.settings, selection)[kind]
                elif kind not in presets:
                    if original_payload.get(kind):
                        raise LocalGenerationError(
                            "旧任务缺少独立预设快照，不能安全保留未修改的角色/画风；请明确选择两者后重跑")
                    presets[kind] = {"prompt": "", "loras": []}
            # Do not reopen the currently configured template or apply today's
            # defaults: only the requested preset and ratio are replaced.
            workflow, seed, final_prompt = build_local_workflow(
                self.settings, payload.model_copy(update={"ratio": options.ratio}), tags,
                workflow_snapshot=original["workflow"], preset_snapshot=presets)
            meta["preset_snapshot"] = presets
        else:
            workflow = copy.deepcopy(original["workflow"])
            if "preset_snapshot" in original:
                meta["preset_snapshot"] = copy.deepcopy(original["preset_snapshot"])
            if options.ratio:
                width, height = SIZES[options.ratio]
                workflow["28"]["inputs"].update(width=width, height=height)
            final_prompt = str(original["final_prompt"])
            if options.adjustment.strip():
                if original.get("template_snapshot"):
                    # Recompose using frozen presets; additions must be stored
                    # exactly once and use the same ordering as favorites.
                    workflow, seed, final_prompt = build_local_workflow(
                        self.settings, payload.model_copy(update={"ratio": options.ratio}), tags,
                        workflow_snapshot=workflow, preset_snapshot=original["preset_snapshot"])
                else:
                    addition = tags[len(str(original.get("tags", ""))):].strip(" ,")
                    final_prompt = ", ".join(part for part in (final_prompt, addition) if part)
                    workflow["11"]["inputs"]["text"] = final_prompt
            seed = secrets.randbelow(2**63 - 1)
        if options.fixed_seed:
            seed = int(original["seed"])
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                node["inputs"]["seed"] = seed
        meta["tags"] = tags
        return workflow, seed, final_prompt

    def remake_image(self, job_id: str, image_id: str, principal: AuthPrincipal,
                     options: RemakeOptions | None = None):
        original = self.get(job_id, principal)
        if original is None or original.status != "succeeded" or not any(
                image.id == image_id for image in original.images):
            raise RemoteJobError("原任务图片不存在或无权访问")
        try:
            source = self._read_meta(job_id)
            if not isinstance(source.get("workflow"), dict) or "seed" not in source:
                raise LocalGenerationError("原任务未保存完整生成配置")
            base = RemoteJobCreateRequest.model_validate(source["payload"])
        except (KeyError, ValueError, LocalGenerationError) as exc:
            raise RemoteJobError("原图缺少可靠的本机任务快照，不能重跑") from exc
        options = options or RemakeOptions()
        if options.task_suite_id:
            raise RemoteJobError("本机重跑尚不支持任务套组")
        if options.ratio and options.ratio not in SIZES:
            raise RemoteJobError("本机重跑不支持该比例")
        try:
            payload = base.model_copy(update={
                "character": options.character or base.character,
                "character_variant": "" if options.character else base.character_variant,
                "style": options.style or base.style,
                "ratio": options.ratio or base.ratio,
                "prompt": str(source.get("tags", base.prompt)),
                "kind": base.kind if base.kind in {"direct", "hq"} else "direct",
            })
            RemoteJobCreateRequest.model_validate(payload.model_dump())
        except ValueError as exc:
            raise RemoteJobError("重跑参数无效") from exc
        now = _now()
        job = RemoteJobResponse(id=uuid.uuid4().hex, status="queued", kind="remake",
                                safety_code=original.safety_code, target_id="local",
                                target_label="本机工作站", deliver_to_im=False,
                                command_preview="重跑本机图片", source_prompt=original.source_prompt,
                                prompt_ids=list(original.prompt_ids),
                                prompt_provenance=copy.deepcopy(original.prompt_provenance),
                                message="本机重跑已排队", created_at=now, updated_at=now)
        self._jobs[job.id] = job
        self._owners[job.id] = principal.subject
        self._admin_exempt_jobs.add(job.id)
        self._persist(job.id)
        meta = {"payload": payload.model_dump(mode="json"),
                "remake_of": job_id, "remake_options": options.model_dump()}
        if source.get("template_snapshot"):
            meta["template_snapshot"] = copy.deepcopy(source["template_snapshot"])
            meta["user_addition"] = source.get("user_addition", "")
        self._write_meta(job.id, meta)
        task = asyncio.create_task(self._run_local(job.id, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job
