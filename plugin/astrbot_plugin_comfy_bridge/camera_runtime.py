from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct local test import
    from workflow_runtime import WorkflowError


DISTANCE_PROMPTS = {
    "": "",
    "extreme_close": "extreme close-up, face focus",
    "close": "close-up",
    "portrait": "portrait, head and shoulders",
    "upper_body": "upper body",
    "cowboy": "cowboy shot",
    "full_body": "full body",
    "wide": "wide shot, environmental composition",
    "very_wide": "very wide shot, expansive environment",
}

YAW_PROMPTS = {
    "": "",
    "front": "front view, facing viewer",
    "three_quarter": "three-quarter view",
    "side": "side view, profile",
    "rear_three_quarter": "rear three-quarter view",
    "back": "from behind",
}

PITCH_PROMPTS = {
    "": "",
    "eye": "eye-level shot",
    "slight_low": "slightly from below, low angle",
    "low": "from below, low angle, perspective",
    "extreme_low": "(from below:2.2), worm's-eye view, extreme low angle, dramatic foreshortening, strong perspective, vanishing point",
    "slight_high": "slightly from above, high angle",
    "high": "from above, high angle, perspective",
    "extreme_high": "(from above:2.2), bird's-eye view, extreme high angle, dramatic foreshortening, strong perspective, vanishing point",
}

LENS_PROMPTS = {
    "": "",
    "normal": "",
    "wide": "wide-angle lens, exaggerated perspective",
    "ultra_wide": "ultra wide-angle lens, exaggerated perspective, strong depth",
    "telephoto": "telephoto lens, compressed perspective",
    "fisheye": "fisheye lens, curved perspective",
}

ROLL_PROMPTS = {
    "": "",
    "level": "",
    "dutch": "dutch angle, tilted composition",
}


@dataclass(frozen=True)
class CameraPlan:
    prompt: str
    distance: str
    yaw: str
    pitch: str
    lens: str
    roll: str
    lora: dict[str, Any] | None


def _choice(options: dict[str, Any], key: str, table: dict[str, str]) -> str:
    value = str(options.get(key, "") or "").strip().casefold()
    if value not in table:
        allowed = "、".join(item for item in table if item) or "无"
        raise WorkflowError(f"相机参数 {key}={value!r} 无效；可用值：{allowed}")
    return value


def compile_camera_options(
    options: dict[str, Any],
    *,
    extreme_lora_name: str = "",
    extreme_lora_strength: float = 0.65,
) -> CameraPlan:
    """Compile deterministic camera tags and an optional DiT-only extreme-angle LoRA.

    Normal framing remains prompt-only.  The auxiliary LoRA is deliberately
    reserved for the two extreme pitch modes so it does not consume quality or
    fight character/style LoRAs during ordinary generation.
    """

    distance = _choice(options, "camera_distance", DISTANCE_PROMPTS)
    yaw = _choice(options, "camera_yaw", YAW_PROMPTS)
    pitch = _choice(options, "camera_pitch", PITCH_PROMPTS)
    lens = _choice(options, "camera_lens", LENS_PROMPTS)
    roll = _choice(options, "camera_roll", ROLL_PROMPTS)
    pieces = [
        DISTANCE_PROMPTS[distance],
        YAW_PROMPTS[yaw],
        PITCH_PROMPTS[pitch],
        LENS_PROMPTS[lens],
        ROLL_PROMPTS[roll],
    ]
    prompt = ", ".join(piece for piece in pieces if piece)

    lora = None
    name = str(extreme_lora_name or "").strip()
    if options.get("camera_extreme_lora") is True and pitch in {"extreme_low", "extreme_high"} and name:
        strength = float(extreme_lora_strength)
        if not 0.0 <= strength <= 2.0:
            raise WorkflowError("极限机位 LoRA 强度必须在 0 到 2 之间。")
        lora = {
            "name": name,
            "strength_model": strength,
            # The tested camera LoRAs are DiT-only.  Keeping CLIP at zero also
            # prevents prompt semantics from drifting when the file happens to
            # expose a CLIP adapter.
            "strength_clip": 0.0,
        }
    return CameraPlan(prompt, distance, yaw, pitch, lens, roll, lora)
