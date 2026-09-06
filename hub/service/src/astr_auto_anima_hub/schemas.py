from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    service: str = "astr-auto-anima-hub"
    version: str
    status: Literal["ok"] = "ok"
    timestamp: datetime


class ProbeStatus(BaseModel):
    name: str
    status: Literal["online", "offline", "missing", "invalid", "unknown"]
    detail: str = ""
    latency_ms: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class WorkstationStatus(BaseModel):
    status: Literal["ready", "degraded", "offline"]
    checked_at: datetime
    probes: list[ProbeStatus]


class MemoryMetrics(BaseModel):
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    utilization_percent: float = Field(ge=0.0, le=100.0)


class GpuMetrics(BaseModel):
    index: int = Field(ge=0)
    name: str
    utilization_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    memory_total_mib: int = Field(ge=0)
    memory_used_mib: int = Field(ge=0)
    memory_free_mib: int = Field(ge=0)
    memory_utilization_percent: float = Field(ge=0.0, le=100.0)
    temperature_c: float | None = None


class WorkstationMetrics(BaseModel):
    collected_at: datetime
    cpu_percent: float = Field(ge=0.0, le=100.0)
    cpu_logical_count: int = Field(ge=1)
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None
    memory: MemoryMetrics
    gpus: list[GpuMetrics] = Field(default_factory=list)


class CharacterDictionaryItem(BaseModel):
    tag: str
    chinese_names: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    copyright: list[str] = Field(default_factory=list)
    gender: list[str] = Field(default_factory=list)
    appearance: list[str] = Field(default_factory=list)
    post_count: int = Field(default=0, ge=0)
    weak_prompt: str
    strong_prompt: str
    disabled: bool = False
    overridden: bool = False


class CharacterDictionaryResponse(BaseModel):
    available: bool
    query: str = ""
    total: int = Field(default=0, ge=0)
    items: list[CharacterDictionaryItem] = Field(default_factory=list)
    message: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)
    pages: int = Field(default=1, ge=1)
    revision: str = "missing"


class CharacterDictionaryUpdateRequest(BaseModel):
    aliases: list[str] | None = Field(default=None, max_length=128)
    copyright: list[str] | None = Field(default=None, max_length=32)
    gender: list[str] | None = Field(default=None, max_length=16)
    appearance: list[str] | None = Field(default=None, max_length=128)
    post_count: int | None = Field(default=None, ge=0)
    disabled: bool | None = None


class CharacterFavoriteWriteRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    mode: Literal["weak", "strong"] = "weak"


class CharacterFavoriteRecord(BaseModel):
    tag: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=120)
    mode: Literal["weak", "strong"] = "weak"
    weak_prompt: str = ""
    strong_prompt: str = ""


class CharacterFavoriteListResponse(BaseModel):
    items: list[CharacterFavoriteRecord] = Field(default_factory=list)
    revision: str = "missing"


class RevisionInfo(BaseModel):
    name: str
    exists: bool
    revision: str | None = None
    modified_at: datetime | None = None
    size: int | None = None


class SyncRevisionsResponse(BaseModel):
    checked_at: datetime
    prompts: RevisionInfo
    presets: RevisionInfo


class PromptRecord(BaseModel):
    id: str
    name: str = ""
    prompt: str
    source_code: str
    safety_code: str
    enabled: bool = True
    weight: int = 1
    categories: list[str] = Field(default_factory=list)


class PromptPage(BaseModel):
    items: list[PromptRecord]
    page: int
    page_size: int
    total: int
    pages: int
    revision: str


class PresetSummary(BaseModel):
    name: str
    kind: Literal["style", "character"]
    prompt: str = ""
    match: list[str] = Field(default_factory=list)
    loras: list[dict[str, Any]] = Field(default_factory=list)
    text_only: bool = False


class PresetListResponse(BaseModel):
    styles: list[PresetSummary]
    characters: list[PresetSummary]
    revision: str


class DeliveryTarget(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["group", "private"]


class DeliveryTargetListResponse(BaseModel):
    targets: list[DeliveryTarget]


class RemoteJobCreateRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=80)
    kind: Literal["direct", "chinese", "reverse", "random", "chaos", "hq", "refine"]
    five_draw: bool = False
    pool_filter: str = Field(default="", max_length=32)
    character: str = Field(default="", max_length=200)
    character_tag_mode: Literal["weak", "strong", "off"] = "weak"
    style: str = Field(default="", max_length=200)
    personal_style_slot: int | None = Field(default=None, ge=1, le=3)
    ratio: Literal["", "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9"] = ""
    sampler: Literal["", "2m", "2m_sde", "2m_sde_gpu"] = ""
    scheduler: Literal[
        "",
        "normal",
        "karras",
        "exponential",
        "sgm_uniform",
        "simple",
        "ddim_uniform",
        "beta",
        "linear_quadratic",
        "kl_optimal",
    ] = ""
    steps: int | None = Field(default=None, ge=1, le=200)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    prompt: str = Field(default="", max_length=100_000)
    safety_code: Literal["N", "H", "S"] = "N"
    reverse_preset: Literal["full", "scene", "action", "character", "safe", "raw"] = "full"
    reverse_categories: list[
        Literal[
            "scene",
            "action",
            "character",
            "appearance",
            "special_features",
            "clothing",
            "composition",
            "other",
            "safety",
        ]
    ] = Field(default_factory=list, max_length=9)
    reverse_only: bool = False
    profile: Literal["", "stable", "beauty", "light", "medium", "seedvr2"] = ""
    parent_job_id: str = Field(default="", max_length=120)
    scale: float | None = Field(default=None, ge=1.0, le=2.0)
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)
    source_image_name: str = Field(default="", max_length=255)
    source_image_data: str = Field(default="", max_length=30_000_000)


class RemoteJobImage(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="image/png", max_length=120)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    download_url: str = Field(min_length=1, max_length=500)


class RemoteJobResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    kind: Literal["direct", "chinese", "reverse", "random", "chaos", "hq", "refine"] = "direct"
    safety_code: Literal["N", "H", "S"] = "N"
    profile: str = Field(default="", max_length=40)
    target_id: str
    target_label: str
    command_preview: str
    message: str = ""
    images: list[RemoteJobImage] = Field(default_factory=list, max_length=20)
    prompt_ids: list[str] = Field(default_factory=list, max_length=20)
    liked_prompt_ids: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime
    updated_at: datetime


class RemoteJobPage(BaseModel):
    items: list[RemoteJobResponse]
    page: int = Field(ge=1)
    pages: int = Field(ge=1)
    total: int = Field(ge=0)


class LoraSpec(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    strength_model: float = Field(default=1.0, ge=-5.0, le=5.0)
    strength_clip: float = Field(default=1.0, ge=-5.0, le=5.0)


class PromptCreateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    prompt: str = Field(min_length=1, max_length=100_000)
    source_code: Literal["B", "G", "D", "C", "R", "P"] = "B"
    safety_code: Literal["N", "H", "S"] = "N"
    enabled: bool = True
    weight: int = Field(default=1, ge=1, le=100)
    categories: list[str] = Field(default_factory=list, max_length=64)


class PromptUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    source_code: Literal["B", "G", "D", "C", "R", "P"] | None = None
    safety_code: Literal["N", "H", "S"] | None = None
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=100)
    categories: list[str] | None = Field(default=None, max_length=64)


class PromptImportRequest(BaseModel):
    prompts: list[PromptCreateRequest] = Field(min_length=1, max_length=10_000)


class PresetWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=100_000)
    match: list[str] = Field(default_factory=list, max_length=128)
    loras: list[LoraSpec] = Field(default_factory=list, max_length=16)


class LiteUserSummary(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    qq: str = Field(pattern=r"^[1-9][0-9]{4,14}$")
    label: str = Field(min_length=1, max_length=120)
    allow_group: bool = True
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LiteUserListResponse(BaseModel):
    items: list[LiteUserSummary]
    revision: str


class LiteUserCreateRequest(BaseModel):
    qq: str = Field(pattern=r"^[1-9][0-9]{4,14}$")
    label: str = Field(default="", max_length=120)
    allow_group: bool = True


class LiteUserUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    allow_group: bool | None = None
    enabled: bool | None = None


class LiteUserIssueResponse(BaseModel):
    action: Literal["created", "rotated"]
    user: LiteUserSummary
    token: str = Field(min_length=32, max_length=200)
    revision: str
    backup: str | None = None


class MutationResponse(BaseModel):
    action: Literal["created", "updated", "deleted", "imported"]
    resource: str
    revision: str
    backup: str | None = None
    count: int = 1


class PromptLikeResponse(BaseModel):
    action: Literal["liked", "already_liked"]
    prompt_id: str
    saved_prompt_id: str
    revision: str


class LoraCatalogItem(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    display_name: str = Field(min_length=1, max_length=200)
    category: Literal["unclassified", "style", "character", "other"] = "unclassified"
    recommended_prompt: str = Field(default="", max_length=20_000)
    enabled: bool = True
    present: bool = True
    size_bytes: int = Field(default=0, ge=0)
    modified_ns: int = Field(default=0, ge=0)


class LoraCatalogResponse(BaseModel):
    items: list[LoraCatalogItem]
    revision: str
    scanned_at: datetime


class LoraCatalogUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: Literal["unclassified", "style", "character", "other"] | None = None
    recommended_prompt: str | None = Field(default=None, max_length=20_000)
    enabled: bool | None = None


class PersonalStyleLora(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    strength: float = Field(default=1.0, ge=-5.0, le=5.0)


class PersonalStyleWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=100_000)
    loras: list[PersonalStyleLora] = Field(min_length=1, max_length=16)


class PersonalStyleRecord(BaseModel):
    slot: int = Field(ge=1, le=3)
    name: str
    prompt: str = ""
    loras: list[PersonalStyleLora]
    style_key: str


class PersonalStyleListResponse(BaseModel):
    items: list[PersonalStyleRecord]
    revision: str
