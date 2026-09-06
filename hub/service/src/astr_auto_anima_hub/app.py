from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
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
from .personal_styles import (
    delete_personal_style,
    list_personal_styles,
    write_personal_style,
)
from .prompt_likes import promote_k_prompt
from .repositories import (
    RepositoryError,
    file_revision,
    list_presets,
    list_prompts,
)
from .remote_jobs import RemoteJobError, RemoteJobManager
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
        yield
        await application.state.remote_jobs.shutdown()

    app = FastAPI(
        title="AstrAutoAnima Hub",
        version=__version__,
        description="Workstation API for AstrBot, ComfyUI and AstrAutoAnima clients.",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.remote_jobs = RemoteJobManager(resolved)

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            version=__version__, timestamp=datetime.now().astimezone()
        )

    @app.get(
        "/api/v1/lite/prompts",
        response_model=PromptPage,
        tags=["lite"],
        dependencies=[Depends(require_reader)],
    )
    async def lite_prompts(
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
