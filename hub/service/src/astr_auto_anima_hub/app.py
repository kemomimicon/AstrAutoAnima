from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .task_suites import SuiteWrite, list_suites, write_suite, delete_suite
from .auth import AuthPrincipal, require_admin, require_reader
from .character_catalog import search_character_dictionary
from .character_management import disable_character, update_character
from .character_favorites import (
    delete_character_favorite,
    list_character_favorites,
    write_character_favorite,
)
from .config import Settings
from .management import (
    create_prompt,
    delete_preset,
    delete_prompt,
    export_prompts,
    import_prompts,
    update_prompt,
    write_preset,
)
from .lite_user_management import (
    create_lite_user,
    delete_lite_user,
    list_lite_users,
    rotate_lite_user_token,
    update_lite_user,
)
from .probes import collect_workstation_status
from .system_metrics import collect_system_metrics
from .lora_catalog import list_style_loras, scan_loras, update_lora
from .civitai_downloads import CivitaiDownloads, DownloadRequest
from .napcat_login import napcat_request, NapcatLoginRequest
from . import service_recovery
from .personal_styles import (
    delete_personal_style,
    list_personal_styles,
    write_personal_style,
)
from .prompt_likes import promote_k_prompt, remove_prompt_favorite
from .repositories import (
    RepositoryError,
    file_revision,
    list_presets,
    list_prompts,
)
from .remote_jobs import RemoteJobError, RemoteJobManager
from .prompt_reports import PromptReports
from .style_gallery import StyleGallery, GalleryUpdate, GalleryGenerate
from .image_storage import ImageStorage, router as image_storage_router
from .idle_guard import admission
from .schemas import (
    HealthResponse,
    DeliveryTargetListResponse,
    LiteUserCreateRequest,
    LiteUserIssueResponse,
    LiteUserListResponse,
    LiteUserUpdateRequest,
    LoraCatalogResponse,
    LoraCatalogUpdateRequest,
    MutationResponse,
    PresetListResponse,
    PresetWriteRequest,
    PersonalStyleListResponse,
    PersonalStyleWriteRequest,
    PromptLikeResponse,
    PromptCreateRequest,
    PromptImportRequest,
    PromptPage,
    PromptUpdateRequest,
    RemoteJobCreateRequest,
    RemakeOptions,
    RemoteJobPage,
    RemoteJobResponse,
    SyncRevisionsResponse,
    WorkstationStatus,
    WorkstationMetrics,
    CharacterDictionaryResponse,
    CharacterDictionaryUpdateRequest,
    CharacterFavoriteListResponse,
    CharacterFavoriteWriteRequest,
)
from .storage import DuplicateResource, ResourceNotFound, RevisionConflict


def _expected_revision(value: str | None) -> str:
    if not value:
        raise HTTPException(
            status_code=428,
            detail="If-Match revision header is required",
        )
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    return normalized.strip('"')


def _actor(device_name: str | None) -> str:
    safe = "".join(
        value for value in str(device_name or "admin") if value.isalnum() or value in "-_. "
    ).strip()
    return f"admin:{safe[:80] or 'unknown'}"


def _raise_management_error(exc: RepositoryError) -> None:
    if isinstance(exc, RevisionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "current_revision": exc.current_revision,
            },
        ) from exc
    if isinstance(exc, ResourceNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, DuplicateResource):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        storage_task = asyncio.create_task(application.state.image_storage.scheduler())
        yield
        storage_task.cancel()
        await asyncio.gather(storage_task, return_exceptions=True)
        await application.state.style_gallery.shutdown()
        await application.state.remote_jobs.shutdown()
        await application.state.civitai_downloads.shutdown()

    app = FastAPI(
        title="AstrAutoAnima Hub",
        version=__version__,
        description="Workstation API for AstrBot, ComfyUI and AstrAutoAnima clients.",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.remote_jobs = RemoteJobManager(resolved)
    app.state.prompt_reports = PromptReports(resolved, app.state.remote_jobs)
    app.state.civitai_downloads = CivitaiDownloads(resolved)
    app.state.style_gallery = StyleGallery(resolved, app.state.remote_jobs)
    app.state.image_storage = ImageStorage(resolved, app.state.remote_jobs)
    app.include_router(image_storage_router)

    @app.middleware('http')
    async def idle_admission(request, call_next):
        if request.method in {'GET', 'HEAD', 'OPTIONS'} or request.url.path == '/api/v1/admin/auto-sleep':
            return await call_next(request)
        try:
            lease = admission(resolved.plugin_data_dir)
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': '实例正在准备休眠，暂不接受新任务或写入'}, status_code=503)
        try:
            return await call_next(request)
        finally:
            if lease:
                lease.close()

    @app.get("/api/v1/visual-presets", dependencies=[Depends(require_reader)])
    async def visual_presets():
        import json
        path = resolved.plugin_dir / "data/aaa_anima_lighting_material_presets_v1.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return {"available": True, "lighting": data["lighting_presets"], "material": data["material_presets"]}
        except (OSError, ValueError, KeyError, TypeError):
            return {"available": False, "lighting": [], "material": [], "message": "光影材质库未安装或损坏"}

    @app.get("/api/v1/gallery", tags=["gallery"])
    async def gallery(principal: AuthPrincipal = Depends(require_reader)):
        try:
            return app.state.style_gallery.view(principal.is_admin)
        except (RepositoryError, OSError, ValueError) as exc:
            raise HTTPException(422, "画廊配置不可读取，请管理员检查专用目录") from exc

    @app.post("/api/v1/admin/gallery/config", tags=["gallery"])
    async def gallery_config(payload: GalleryUpdate, principal: AuthPrincipal = Depends(require_admin)):
        try:
            return await app.state.style_gallery.update(payload)
        except RepositoryError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/admin/gallery/generate", tags=["gallery"])
    async def gallery_generate(payload: GalleryGenerate, principal: AuthPrincipal = Depends(require_admin)):
        try:
            return await app.state.style_gallery.generate(payload, principal)
        except (RepositoryError, RemoteJobError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/v1/gallery/images/{image_id}", tags=["gallery"], dependencies=[Depends(require_reader)])
    async def gallery_image(image_id: str):
        try:
            path, content_type = app.state.style_gallery.image(image_id)
            return FileResponse(path, media_type=content_type, headers={"Cache-Control": "no-store"})
        except (RepositoryError, RemoteJobError, OSError) as exc:
            raise HTTPException(404, "图片不可用、已过期或未通过安全审核") from exc

    @app.get('/api/v1/admin/services/recovery', dependencies=[Depends(require_admin)])
    def recovery_status():
        return {**service_recovery.recovery_config(), 'operation': service_recovery.read_status(resolved.hub_state_dir)}

    @app.post('/api/v1/admin/services/restart')
    def restart_services(principal: Annotated[AuthPrincipal, Depends(require_admin)], confirmed: bool = False):
        if not confirmed:
            raise HTTPException(422, '必须确认：生图、QQ连接及Hub会中断，请先停止任务；训练不会被本操作主动结束')
        try:
            return service_recovery.submit(resolved.hub_state_dir, f'{principal.role}:{principal.subject}')
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/v1/admin/napcat/status', dependencies=[Depends(require_admin)])
    async def napcat_status():
        try:
            return await napcat_request(NapcatLoginRequest(), status_only=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, '暂时无法查询 NapCat 状态；这不等于 QQ 已掉线')

    @app.post("/api/v1/admin/napcat/accounts", dependencies=[Depends(require_admin)])
    async def napcat_accounts(payload: NapcatLoginRequest):
        try:
            return await napcat_request(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, "无法连接本机NapCat；请检查服务和配置文件")

    @app.post('/api/v1/admin/napcat/qrcode', dependencies=[Depends(require_admin)])
    async def napcat_qrcode(payload: NapcatLoginRequest):
        try:
            return await napcat_request(payload, refresh_qr=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, '无法读取本机 NapCat 二维码，请检查服务状态')

    @app.post("/api/v1/admin/napcat/login", dependencies=[Depends(require_admin)])
    async def napcat_login(payload: NapcatLoginRequest):
        try:
            return await napcat_request(payload, login=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, "NapCat 登录请求失败，请到WebUI检查；未修改登录配置")

    @app.get("/api/v1/admin/civitai/models/{model_id}", dependencies=[Depends(require_admin)])
    async def civitai_model(model_id: int):
        try:
            return await app.state.civitai_downloads.versions(model_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/v1/admin/civitai/versions/{version_id}", dependencies=[Depends(require_admin)])
    async def civitai_version(version_id: int):
        if version_id <= 0:
            raise HTTPException(422, "版本ID必须为正整数")
        try:
            data = await app.state.civitai_downloads.preview(version_id)
            # Do not relay arbitrary HTML, images or signed download URLs to clients.
            return {"id": data.get("id"), "name": data.get("name"), "base_model": data.get("baseModel"),
                    "trained_words": data.get("trainedWords", []), "model": data.get("model", {}),
                    "files": [{k: item.get(k) for k in ("id", "name", "sizeKB", "hashes", "metadata", "type", "virusScanResult", "pickleScanResult")} for item in data.get("files", [])]}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, "Civitai 元数据服务暂不可用")

    @app.get("/api/v1/admin/civitai/downloads", dependencies=[Depends(require_admin)])
    async def civitai_jobs():
        return {"enabled": app.state.civitai_downloads.enabled, "jobs": app.state.civitai_downloads.list_jobs()}

    @app.post("/api/v1/admin/civitai/downloads", dependencies=[Depends(require_admin)], status_code=202)
    async def civitai_download(payload: DownloadRequest):
        try:
            return await app.state.civitai_downloads.submit(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, "无法创建下载任务")

    @app.post("/api/v1/admin/civitai/downloads/{job_id}/cancel", dependencies=[Depends(require_admin)])
    async def civitai_cancel(job_id: str):
        try:
            return await app.state.civitai_downloads.cancel(job_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/v1/admin/civitai/downloads/{job_id}/resume", dependencies=[Depends(require_admin)])
    async def civitai_resume(job_id: str):
        try:
            return await app.state.civitai_downloads.resume(job_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            raise HTTPException(502, "续传任务创建失败，请检查网络")

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            version=__version__, timestamp=datetime.now().astimezone()
        )

    @app.post("/api/v1/lite/jobs/{job_id}/images/{image_id}/remake", response_model=RemoteJobResponse, status_code=202)
    async def remake_image(job_id: str, image_id: str, principal: Annotated[AuthPrincipal, Depends(require_reader)], payload: RemakeOptions | None = None):
        try:
            return app.state.remote_jobs.remake_image(job_id, image_id, principal, payload)
        except RemoteJobError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get(
        "/api/v1/lite/prompts",
        response_model=PromptPage,
        tags=["lite"],
        dependencies=[Depends(require_reader)],
    )
    async def lite_prompts(
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        source: str = Query(default="", max_length=16),
        safety: str = Query(default="", max_length=8),
        query: str = Query(default="", max_length=500),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=200),
    ) -> PromptPage:
        """Return enabled prompt records without exposing write operations."""

        try:
            result = list_prompts(
                resolved.prompt_pool_path,
                owner=principal.subject,
                source=source,
                safety=safety,
                query=query,
                enabled=True,
                page=page,
                page_size=page_size,
            )
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if page > result.pages:
            raise HTTPException(status_code=404, detail="page out of range")
        return result

    @app.post("/api/v1/lite/jobs/{job_id}/images/{image_id}/report")
    def report_prompt(job_id: str, image_id: str, principal: Annotated[AuthPrincipal, Depends(require_reader)]):
        try:
            return app.state.prompt_reports.submit(job_id, image_id, principal)
        except (RepositoryError, RemoteJobError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/v1/internal/qq-image-actions/{ticket_id}', include_in_schema=False)
    def qq_image_action(ticket_id: str):
        # Possession of a one-use capability created on the shared local disk is
        # the authorization. No QQ number/job/path is accepted in HTTP payloads.
        from .qq_image_actions import handle_qq_action
        try:
            return handle_qq_action(resolved, app.state.prompt_reports, app.state.remote_jobs, ticket_id)
        except (RepositoryError, OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/v1/admin/prompt-reports", dependencies=[Depends(require_admin)])
    def prompt_reports():
        return app.state.prompt_reports.list()

    @app.get("/api/v1/admin/prompt-reports/{report_id}/image", dependencies=[Depends(require_admin)])
    def report_image(report_id: str):
        try:
            path, mime = app.state.prompt_reports.image(report_id)
            return FileResponse(path, media_type=mime)
        except (RepositoryError, RemoteJobError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/v1/admin/prompt-reports/{report_id}/{action}")
    def resolve_report(report_id: str, action: str, principal: Annotated[AuthPrincipal, Depends(require_admin)], confirmed: bool = False):
        if not confirmed: raise HTTPException(409, '需要二次确认')
        try:
            return app.state.prompt_reports.resolve(report_id, action, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.post("/api/v1/lite/prompt-favorites/{prompt_id}", response_model=PromptLikeResponse)
    def favorite_prompt(prompt_id: str, principal: Annotated[AuthPrincipal, Depends(require_reader)]):
        try:
            return promote_k_prompt(resolved, prompt_id, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete("/api/v1/lite/prompt-favorites/{prompt_id}")
    def unfavorite_prompt(prompt_id: str, principal: Annotated[AuthPrincipal, Depends(require_reader)]):
        try:
            result = remove_prompt_favorite(resolved, prompt_id, principal)
            app.state.remote_jobs.unmark_liked(prompt_id, principal)
            return result
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/lite/presets",
        response_model=PresetListResponse,
        tags=["lite"],
        dependencies=[Depends(require_reader)],
    )
    async def lite_presets() -> PresetListResponse:
        """Return character and style names for Lite command composition."""

        try:
            return list_presets(resolved.preset_path)
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v1/lite/characters",
        response_model=CharacterDictionaryResponse,
        tags=["lite"],
        dependencies=[Depends(require_reader)],
    )
    async def lite_character_dictionary(
        query: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
        page: int = Query(default=1, ge=1),
    ) -> CharacterDictionaryResponse:
        """Search the server-local Chinese/English character dictionary."""

        return search_character_dictionary(
            resolved.character_dictionary_path,
            query=query,
            limit=limit,
            page=page,
            edits_path=resolved.character_dictionary_edits_path,
        )

    @app.get(
        "/api/v1/lite/character-favorites",
        response_model=CharacterFavoriteListResponse,
        tags=["lite"],
    )
    def lite_character_favorites(
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> CharacterFavoriteListResponse:
        try:
            return list_character_favorites(resolved, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.put(
        "/api/v1/lite/character-favorites/{tag}",
        response_model=CharacterFavoriteListResponse,
        tags=["lite"],
    )
    def lite_character_favorite_write(
        tag: str,
        payload: CharacterFavoriteWriteRequest,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> CharacterFavoriteListResponse:
        try:
            return write_character_favorite(
                resolved, principal, tag, payload, _expected_revision(if_match)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/lite/character-favorites/{tag}",
        response_model=CharacterFavoriteListResponse,
        tags=["lite"],
    )
    def lite_character_favorite_delete(
        tag: str,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> CharacterFavoriteListResponse:
        try:
            return delete_character_favorite(
                resolved, principal, tag, _expected_revision(if_match)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/lite/style-loras",
        response_model=LoraCatalogResponse,
        tags=["lite"],
        dependencies=[Depends(require_reader)],
    )
    async def lite_style_loras() -> LoraCatalogResponse:
        try:
            return list_style_loras(resolved)
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post('/api/v1/lite/jobs/{job_id}/cancel-suite')
    def cancel_task_suite(job_id: str, principal: Annotated[AuthPrincipal, Depends(require_reader)]):
        try:
            return app.state.remote_jobs.cancel_suite(job_id, principal)
        except RemoteJobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get('/api/v1/lite/task-suites')
    def task_suites_list(principal: Annotated[AuthPrincipal, Depends(require_reader)]):
        try:
            return list_suites(resolved, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.post('/api/v1/lite/task-suites')
    def task_suites_create(payload: SuiteWrite, principal: Annotated[AuthPrincipal, Depends(require_reader)],
                           if_match: Annotated[str | None, Header(alias='If-Match')] = None):
        try:
            return write_suite(resolved, principal, payload, _expected_revision(if_match))
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.put('/api/v1/lite/task-suites/{identifier}')
    def task_suites_edit(identifier: str, payload: SuiteWrite, principal: Annotated[AuthPrincipal, Depends(require_reader)],
                         if_match: Annotated[str | None, Header(alias='If-Match')] = None):
        try:
            visible = list_suites(resolved, principal)['items']
            if not any(i['id'] == identifier and i['editable'] for i in visible):
                raise ResourceNotFound('套组不存在或无权修改')
            return write_suite(resolved, principal, payload, _expected_revision(if_match), identifier)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete('/api/v1/lite/task-suites/{identifier}')
    def task_suites_delete(identifier: str, principal: Annotated[AuthPrincipal, Depends(require_reader)],
                           if_match: Annotated[str | None, Header(alias='If-Match')] = None):
        try:
            return delete_suite(resolved, principal, identifier, _expected_revision(if_match))
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/lite/personal-styles",
        response_model=PersonalStyleListResponse,
        tags=["lite"],
    )
    async def lite_personal_styles(
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> PersonalStyleListResponse:
        try:
            return list_personal_styles(resolved, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.put(
        "/api/v1/lite/personal-styles/{slot}",
        response_model=PersonalStyleListResponse,
        tags=["lite"],
    )
    def lite_personal_style_write(
        slot: int,
        payload: PersonalStyleWriteRequest,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> PersonalStyleListResponse:
        try:
            return write_personal_style(
                resolved, principal, slot, payload, _expected_revision(if_match)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/lite/personal-styles/{slot}",
        response_model=PersonalStyleListResponse,
        tags=["lite"],
    )
    def lite_personal_style_delete(
        slot: int,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> PersonalStyleListResponse:
        try:
            return delete_personal_style(
                resolved, principal, slot, _expected_revision(if_match)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/lite/delivery-targets",
        response_model=DeliveryTargetListResponse,
        tags=["lite"],
    )
    async def lite_delivery_targets(
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> DeliveryTargetListResponse:
        try:
            return app.state.remote_jobs.targets(principal)
        except RemoteJobError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/api/v1/lite/jobs",
        response_model=RemoteJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["lite"],
    )
    async def lite_job_create(
        payload: RemoteJobCreateRequest,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> RemoteJobResponse:
        try:
            return app.state.remote_jobs.create(payload, principal)
        except RemoteJobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/v1/lite/jobs",
        response_model=RemoteJobPage,
        tags=["lite"],
    )
    async def lite_job_history(
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
        kind: str = Query(default="", max_length=20),
        job_status: str = Query(default="", alias="status", max_length=20),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=30, ge=1, le=100),
    ) -> RemoteJobPage:
        try:
            return app.state.remote_jobs.list(
                principal,
                kind=kind,
                status=job_status,
                page=page,
                page_size=page_size,
            )
        except RemoteJobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/v1/lite/jobs/{job_id}",
        response_model=RemoteJobResponse,
        tags=["lite"],
    )
    async def lite_job_status(
        job_id: str,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> RemoteJobResponse:
        job = app.state.remote_jobs.get(job_id, principal)
        if job is None:
            raise HTTPException(status_code=404, detail="remote job not found")
        return job

    @app.get(
        "/api/v1/lite/jobs/{job_id}/images/{image_id}",
        tags=["lite"],
    )
    async def lite_job_image(
        job_id: str,
        image_id: str,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> FileResponse:
        result = app.state.remote_jobs.get_image(job_id, image_id, principal)
        if result is None:
            raise HTTPException(status_code=404, detail="remote job image not found")
        image, path = result
        return FileResponse(
            path,
            media_type=image.content_type,
            filename=image.filename,
        )

    @app.post(
        "/api/v1/lite/jobs/{job_id}/likes/{prompt_id}",
        response_model=PromptLikeResponse,
        tags=["lite"],
    )
    def lite_job_like_prompt(
        job_id: str,
        prompt_id: str,
        principal: Annotated[AuthPrincipal, Depends(require_reader)],
    ) -> PromptLikeResponse:
        job = app.state.remote_jobs.get(job_id, principal)
        if job is None:
            raise HTTPException(status_code=404, detail="remote job not found")
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail="only successful jobs can be liked")
        if prompt_id not in job.prompt_ids:
            raise HTTPException(status_code=404, detail="prompt is not part of this job")
        try:
            result = promote_k_prompt(resolved, prompt_id, principal)
        except RepositoryError as exc:
            _raise_management_error(exc)
        app.state.remote_jobs.mark_liked(job_id, prompt_id, principal)
        return result

    @app.get(
        "/api/v1/workstation/status",
        response_model=WorkstationStatus,
        tags=["system"],
        dependencies=[Depends(require_admin)],
    )
    async def workstation_status() -> WorkstationStatus:
        return await collect_workstation_status(resolved)

    @app.get(
        "/api/v1/workstation/metrics",
        response_model=WorkstationMetrics,
        tags=["system"],
        dependencies=[Depends(require_admin)],
    )
    async def workstation_metrics() -> WorkstationMetrics:
        return await asyncio.to_thread(collect_system_metrics)

    @app.get(
        "/api/v1/admin/characters",
        response_model=CharacterDictionaryResponse,
        tags=["characters"],
        dependencies=[Depends(require_admin)],
    )
    async def admin_characters(
        query: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        include_disabled: bool = True,
    ) -> CharacterDictionaryResponse:
        result = search_character_dictionary(
            resolved.character_dictionary_path,
            query=query,
            limit=page_size,
            page=page,
            edits_path=resolved.character_dictionary_edits_path,
            include_disabled=include_disabled,
        )
        edit_revision = (
            file_revision(
                resolved.character_dictionary_edits_path,
                "character_dictionary",
            ).revision
            or "missing"
        )
        return result.model_copy(update={"revision": edit_revision})

    @app.patch(
        "/api/v1/admin/characters/{tag}",
        response_model=MutationResponse,
        tags=["characters"],
        dependencies=[Depends(require_admin)],
    )
    def admin_character_update(
        tag: str,
        payload: CharacterDictionaryUpdateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        try:
            return update_character(
                resolved, tag, payload, _expected_revision(if_match), _actor(device_name)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/admin/characters/{tag}",
        response_model=MutationResponse,
        tags=["characters"],
        dependencies=[Depends(require_admin)],
    )
    def admin_character_delete(
        tag: str,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        try:
            return disable_character(
                resolved, tag, _expected_revision(if_match), _actor(device_name)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/admin/loras",
        response_model=LoraCatalogResponse,
        tags=["loras"],
    )
    def admin_loras(
        principal: Annotated[AuthPrincipal, Depends(require_admin)],
    ) -> LoraCatalogResponse:
        try:
            return scan_loras(resolved, f"admin:{principal.subject}")
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.patch(
        "/api/v1/admin/loras/{relative_path:path}",
        response_model=MutationResponse,
        tags=["loras"],
    )
    def admin_lora_update(
        relative_path: str,
        payload: LoraCatalogUpdateRequest,
        principal: Annotated[AuthPrincipal, Depends(require_admin)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> MutationResponse:
        try:
            return update_lora(
                resolved,
                relative_path,
                payload,
                _expected_revision(if_match),
                f"admin:{principal.subject}",
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/admin/lite-users",
        response_model=LiteUserListResponse,
        tags=["users"],
        dependencies=[Depends(require_admin)],
    )
    def lite_user_list() -> LiteUserListResponse:
        try:
            return list_lite_users(resolved)
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/api/v1/admin/lite-users",
        response_model=LiteUserIssueResponse,
        tags=["users"],
        dependencies=[Depends(require_admin)],
    )
    def lite_user_create(
        payload: LiteUserCreateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> LiteUserIssueResponse:
        expected = _expected_revision(if_match)
        try:
            return create_lite_user(resolved, payload, expected, _actor(device_name))
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.patch(
        "/api/v1/admin/lite-users/{qq}",
        response_model=MutationResponse,
        tags=["users"],
        dependencies=[Depends(require_admin)],
    )
    def lite_user_update(
        qq: str,
        payload: LiteUserUpdateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return update_lite_user(
                resolved, qq, payload, expected, _actor(device_name)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.post(
        "/api/v1/admin/lite-users/{qq}/rotate",
        response_model=LiteUserIssueResponse,
        tags=["users"],
        dependencies=[Depends(require_admin)],
    )
    def lite_user_rotate(
        qq: str,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> LiteUserIssueResponse:
        expected = _expected_revision(if_match)
        try:
            return rotate_lite_user_token(
                resolved, qq, expected, _actor(device_name)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/admin/lite-users/{qq}",
        response_model=MutationResponse,
        tags=["users"],
        dependencies=[Depends(require_admin)],
    )
    def lite_user_delete(
        qq: str,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return delete_lite_user(
                resolved, qq, expected, _actor(device_name)
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/sync/revisions",
        response_model=SyncRevisionsResponse,
        tags=["sync"],
        dependencies=[Depends(require_admin)],
    )
    async def sync_revisions() -> SyncRevisionsResponse:
        try:
            return SyncRevisionsResponse(
                checked_at=datetime.now().astimezone(),
                prompts=file_revision(resolved.prompt_pool_path, "prompts"),
                presets=file_revision(resolved.preset_path, "presets"),
            )
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v1/prompts",
        response_model=PromptPage,
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    async def prompts(
        source: str = Query(default="", max_length=16),
        safety: str = Query(default="", max_length=8),
        query: str = Query(default="", max_length=500),
        enabled: bool | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=200),
    ) -> PromptPage:
        try:
            result = list_prompts(
                resolved.prompt_pool_path,
                source=source,
                safety=safety,
                query=query,
                enabled=enabled,
                page=page,
                page_size=page_size,
            )
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if page > result.pages:
            raise HTTPException(status_code=404, detail="page out of range")
        return result

    @app.get(
        "/api/v1/prompts/export",
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    async def prompt_export(
        response: Response,
        source: str = Query(default="", max_length=16),
        safety: str = Query(default="", max_length=8),
        query: str = Query(default="", max_length=500),
    ) -> dict[str, Any]:
        try:
            payload = export_prompts(
                resolved.prompt_pool_path,
                source=source,
                safety=safety,
                query=query,
            )
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response.headers["Content-Disposition"] = (
            'attachment; filename="astr_auto_anima_prompts.json"'
        )
        return payload

    @app.post(
        "/api/v1/prompts",
        response_model=MutationResponse,
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    def prompt_create(
        payload: PromptCreateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return create_prompt(resolved, payload, expected, _actor(device_name))
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.patch(
        "/api/v1/prompts/{prompt_id}",
        response_model=MutationResponse,
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    def prompt_update(
        prompt_id: str,
        payload: PromptUpdateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return update_prompt(
                resolved,
                prompt_id,
                payload,
                expected,
                _actor(device_name),
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/prompts/{prompt_id}",
        response_model=MutationResponse,
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    def prompt_delete(
        prompt_id: str,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return delete_prompt(
                resolved,
                prompt_id,
                expected,
                _actor(device_name),
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.post(
        "/api/v1/prompts/import",
        response_model=MutationResponse,
        tags=["prompts"],
        dependencies=[Depends(require_admin)],
    )
    def prompt_import(
        payload: PromptImportRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return import_prompts(
                resolved,
                payload,
                expected,
                _actor(device_name),
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.get(
        "/api/v1/presets",
        response_model=PresetListResponse,
        tags=["presets"],
        dependencies=[Depends(require_admin)],
    )
    async def presets() -> PresetListResponse:
        try:
            return list_presets(resolved.preset_path)
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/api/v1/presets/{kind}",
        response_model=MutationResponse,
        tags=["presets"],
        dependencies=[Depends(require_admin)],
    )
    def preset_create(
        kind: str,
        payload: PresetWriteRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return write_preset(
                resolved,
                kind,
                payload,
                expected,
                _actor(device_name),
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.put(
        "/api/v1/presets/{kind}/{name}",
        response_model=MutationResponse,
        tags=["presets"],
        dependencies=[Depends(require_admin)],
    )
    def preset_update(
        kind: str,
        name: str,
        payload: PresetWriteRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return write_preset(
                resolved,
                kind,
                payload,
                expected,
                _actor(device_name),
                previous_name=name,
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    @app.delete(
        "/api/v1/presets/{kind}/{name}",
        response_model=MutationResponse,
        tags=["presets"],
        dependencies=[Depends(require_admin)],
    )
    def preset_delete(
        kind: str,
        name: str,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
        device_name: Annotated[str | None, Header(alias="X-Device-Name")] = None,
    ) -> MutationResponse:
        expected = _expected_revision(if_match)
        try:
            return delete_preset(
                resolved,
                kind,
                name,
                expected,
                _actor(device_name),
            )
        except RepositoryError as exc:
            _raise_management_error(exc)

    if resolved.web_root is not None:
        app.mount(
            "/",
            StaticFiles(directory=str(resolved.web_root), html=True),
            name="web-app",
        )

    return app


app = create_app()
