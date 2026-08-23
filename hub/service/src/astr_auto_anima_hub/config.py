from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 6278
    admin_token: str = ""
    lite_token: str = ""
    legacy_lite_qq: str = ""
    astrbot_url: str = "http://127.0.0.1:6185"
    astrbot_api_key: str = ""
    astrbot_bot_id: str = "your-bot-id"
    comfyui_url: str = "http://127.0.0.1:8188"
    request_timeout_seconds: float = 4.0
    plugin_dir: Path = Path(
        "/workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge"
    )
    plugin_data_dir: Path = Path(
        "/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge"
    )
    comfyui_root: Path = Path("/workspace/ComfyUI")
    prompt_pool_override: Path | None = None
    preset_override: Path | None = None
    delivery_targets_override: Path | None = None
    lite_users_override: Path | None = None
    remote_job_timeout_seconds: float = 1800.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("AAH_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int_env("AAH_PORT", 6278),
            admin_token=os.getenv("AAH_ADMIN_TOKEN", "").strip(),
            lite_token=os.getenv("AAH_LITE_TOKEN", "").strip(),
            legacy_lite_qq=os.getenv("AAH_LITE_TOKEN_QQ", "").strip(),
            astrbot_url=os.getenv(
                "AAH_ASTRBOT_URL", "http://127.0.0.1:6185"
            ).strip(),
            astrbot_api_key=os.getenv("AAH_ASTRBOT_API_KEY", "").strip(),
            astrbot_bot_id=os.getenv("AAH_ASTRBOT_BOT_ID", "your-bot-id").strip(),
            comfyui_url=os.getenv(
                "AAH_COMFYUI_URL", "http://127.0.0.1:8188"
            ).strip(),
            request_timeout_seconds=_float_env(
                "AAH_REQUEST_TIMEOUT_SECONDS", 4.0
            ),
            plugin_dir=Path(
                os.getenv(
                    "AAH_PLUGIN_DIR",
                    "/workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge",
                )
            ).expanduser(),
            plugin_data_dir=Path(
                os.getenv(
                    "AAH_PLUGIN_DATA_DIR",
                    "/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge",
                )
            ).expanduser(),
            comfyui_root=Path(
                os.getenv("AAH_COMFYUI_ROOT", "/workspace/ComfyUI")
            ).expanduser(),
            prompt_pool_override=(
                Path(os.environ["AAH_PROMPT_POOL_PATH"]).expanduser()
                if os.getenv("AAH_PROMPT_POOL_PATH", "").strip()
                else None
            ),
            preset_override=(
                Path(os.environ["AAH_PRESET_PATH"]).expanduser()
                if os.getenv("AAH_PRESET_PATH", "").strip()
                else None
            ),
            delivery_targets_override=(
                Path(os.environ["AAH_DELIVERY_TARGETS_PATH"]).expanduser()
                if os.getenv("AAH_DELIVERY_TARGETS_PATH", "").strip()
                else None
            ),
            lite_users_override=(
                Path(os.environ["AAH_LITE_USERS_PATH"]).expanduser()
                if os.getenv("AAH_LITE_USERS_PATH", "").strip()
                else None
            ),
            remote_job_timeout_seconds=_float_env(
                "AAH_REMOTE_JOB_TIMEOUT_SECONDS", 1800.0
            ),
        )

    @property
    def prompt_pool_path(self) -> Path:
        return self.prompt_pool_override or (
            self.plugin_data_dir / "anima_random_prompt_pool.json"
        )

    @property
    def preset_path(self) -> Path:
        return self.preset_override or (self.plugin_data_dir / "presets.json")

    @property
    def output_dir(self) -> Path:
        return self.comfyui_root / "output"

    @property
    def delivery_targets_path(self) -> Path:
        return self.delivery_targets_override or (
            self.hub_state_dir / "delivery_targets.json"
        )

    @property
    def lite_users_path(self) -> Path:
        return self.lite_users_override or (self.hub_state_dir / "lite_users.json")

    @property
    def hub_state_dir(self) -> Path:
        return self.plugin_data_dir / "hub_state"

    @property
    def backup_dir(self) -> Path:
        return self.hub_state_dir / "backups"

    @property
    def trash_dir(self) -> Path:
        return self.hub_state_dir / "trash"

    @property
    def audit_log_path(self) -> Path:
        return self.hub_state_dir / "audit.jsonl"

    @property
    def remote_job_store_dir(self) -> Path:
        return self.hub_state_dir / "remote_jobs"

    def validate_for_startup(self) -> None:
        if len(self.admin_token) < 32:
            raise ValueError(
                "AAH_ADMIN_TOKEN must contain at least 32 characters before startup"
            )
        if self.lite_token and len(self.lite_token) < 32:
            raise ValueError(
                "AAH_LITE_TOKEN must contain at least 32 characters when configured"
            )
        if self.lite_token and self.lite_token == self.admin_token:
            raise ValueError("AAH_LITE_TOKEN must differ from AAH_ADMIN_TOKEN")
        if self.legacy_lite_qq and not (
            self.legacy_lite_qq.isdigit()
            and 5 <= len(self.legacy_lite_qq) <= 15
            and not self.legacy_lite_qq.startswith("0")
        ):
            raise ValueError("AAH_LITE_TOKEN_QQ must be a valid QQ number")
        if self.legacy_lite_qq and not self.lite_token:
            raise ValueError("AAH_LITE_TOKEN_QQ requires AAH_LITE_TOKEN")
        if not (1 <= self.port <= 65535):
            raise ValueError("AAH_PORT must be between 1 and 65535")
        if self.request_timeout_seconds <= 0:
            raise ValueError("AAH_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.remote_job_timeout_seconds <= 0:
            raise ValueError("AAH_REMOTE_JOB_TIMEOUT_SECONDS must be positive")
        if not self.astrbot_bot_id or any(
            value not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for value in self.astrbot_bot_id
        ):
            raise ValueError("AAH_ASTRBOT_BOT_ID contains invalid characters")
