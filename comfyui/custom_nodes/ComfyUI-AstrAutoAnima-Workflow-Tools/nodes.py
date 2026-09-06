from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image


_CONTROL_MARKERS = (
    "final:",
    "assistant:",
    "user:",
    "system:",
    "filename:",
    "file name:",
    "eos",
    "end of turn",
)

_DROP_TAG_PREFIXES = (
    "artist:",
    "copyright:",
    "model:",
    "quality:",
    "score_",
    "score ",
    "rating:",
)

_DROP_TAGS = {
    "masterpiece",
    "best quality",
    "high quality",
    "worst quality",
    "low quality",
    "normal quality",
    "absurdres",
    "highres",
    "official art",
    "ai generated",
}

_SEXUAL_MARKERS = {
    "sex",
    "sexual intercourse",
    "penetration",
    "vaginal penetration",
    "anal penetration",
    "oral sex",
    "fellatio",
    "cunnilingus",
    "masturbation",
    "handjob",
    "footjob",
    "cum",
    "ejaculation",
    "orgasm",
    "genital focus",
    "pussy focus",
    "penis focus",
    "anus focus",
}

_NSFW_MARKERS = {
    "nude",
    "naked",
    "completely nude",
    "full frontal nudity",
    "nipples",
    "areolae",
    "pussy",
    "vagina",
    "penis",
    "testicles",
    "anus",
    "spread legs",
    "explicit nudity",
}

_ACTION_WORDS = {
    "standing", "sitting", "lying", "kneeling", "crouching", "walking",
    "running", "jumping", "flying", "holding", "carrying", "hugging",
    "kissing", "looking at viewer", "looking back", "reaching", "dancing",
    "fighting", "sleeping", "eating", "drinking", "reading", "smiling",
    "crying", "laughing", "posing", "arms up", "hands on hips",
}

_SCENE_WORDS = {
    "outdoors", "indoors", "street", "city", "forest", "beach", "ocean",
    "mountain", "room", "bedroom", "classroom", "office", "restaurant",
    "night", "day", "sunset", "sunrise", "rain", "snow", "cloudy",
    "background", "sky", "water", "garden", "park", "train station",
}

_COMPOSITION_WORDS = {
    "close-up", "upper body", "full body", "cowboy shot", "wide shot",
    "from above", "from below", "low angle", "high angle", "dutch angle",
    "side view", "back view", "profile", "depth of field", "bokeh",
    "looking at viewer", "portrait", "landscape", "centered composition",
}

_CLOTHING_WORDS = {
    "dress", "shirt", "skirt", "shorts", "pants", "jacket", "coat", "hoodie",
    "uniform", "kimono", "swimsuit", "bikini", "underwear", "lingerie",
    "stockings", "thighhighs", "socks", "boots", "shoes", "gloves", "hat",
    "ribbon", "necklace", "earrings", "armor", "cape", "raincoat",
}

_APPEARANCE_WORDS = {
    "hair", "eyes", "skin", "freckles", "mole",
    "twintails", "ponytail", "braid", "bangs", "long hair", "short hair",
    "blush", "smile", "open mouth", "closed eyes",
}

_SPECIAL_FEATURE_WORDS = {
    "animal ears", "fox ears", "wolf ears", "cat ears", "dog ears",
    "bunny ears", "rabbit ears", "horse ears", "mouse ears", "bear ears",
    "tail", "fox tail", "wolf tail", "cat tail", "dog tail", "dragon tail",
    "multiple tails", "wings", "feathered wings", "bat wings", "dragon wings",
    "halo", "horns", "antlers", "fangs", "claws", "paw", "paws",
    "scales", "fin", "fins", "gills", "tentacles", "kemonomimi",
}

_TRAINING_NOISE_TAGS = {
    *_DROP_TAGS,
    "watermark", "signature", "artist name", "username", "logo", "text",
    "english text", "chinese text", "japanese text", "translated", "commentary",
    "lowres", "jpeg artifacts", "compression artifacts", "blurry", "bad anatomy",
    "bad hands", "extra digits", "missing fingers", "censored", "mosaic censoring",
}

_TRAINING_NOISE_PREFIXES = (
    *_DROP_TAG_PREFIXES,
    "source:",
    "meta:",
)

_STYLE_WORDS = {
    "anime coloring", "flat color", "flat colors", "lineart", "no lineart",
    "sketch", "oekaki", "watercolor", "oil painting", "pixel art", "3d",
    "photorealistic", "realistic", "monochrome", "greyscale", "grayscale",
    "pastel colors", "limited palette", "high contrast", "low contrast",
    "chromatic aberration", "film grain", "halftone", "impasto",
}

_SUBJECT_TAG_RE = re.compile(r"^(?:[1-9]\d*|multiple)\s+(?:girls?|boys?|women|men|others?)$")
_COUNT_CONFLICT_RE = re.compile(r"^(?P<count>[1-9]\d*|multiple)\s+(?P<kind>girls?|boys?|women|men|others?)$")

_TRAINING_CATEGORY_ORDER = (
    "subject",
    "appearance",
    "clothing",
    "action",
    "composition",
    "scene",
    "relation",
    "style",
    "other",
)


def _first(value: Any, default: Any = None) -> Any:
    while isinstance(value, (list, tuple)):
        if not value:
            return default
        value = value[0]
    return default if value is None else value


def _flatten_strings(value: Any) -> list[str]:
    result: list[str] = []

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
            return
        text = str(item).strip()
        if text:
            result.append(text)

    visit(value)
    return result


def _count_records(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, dict):
        return 1
    if isinstance(value, (list, tuple)):
        if not value:
            return 0
        if all(isinstance(item, dict) for item in value):
            return len(value)
        counts = [_count_records(item) for item in value]
        return max(counts) if counts else 0
    return 1


def _split_tags(value: Any) -> list[str]:
    tags: list[str] = []
    for text in _flatten_strings(value):
        for raw in re.split(r"[,\n;]+", text):
            tag = raw.strip().strip("[]{}\"'")
            tag = tag.replace("_", " ")
            tag = re.sub(r"\s+", " ", tag).strip().lower()
            if tag:
                tags.append(tag)
    return tags


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        clean = re.sub(r"\s+", " ", str(item).strip().lower())
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


def _is_drop_tag(tag: str) -> bool:
    lower = tag.lower().strip()
    return lower in _DROP_TAGS or any(lower.startswith(prefix) for prefix in _DROP_TAG_PREFIXES)


def _contains_keyword(tag: str, words: set[str]) -> bool:
    lower = tag.lower()
    return any(
        word == lower or re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", lower)
        for word in words
    )


def _flatten_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            records.append(item)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return records


def _training_tag_category(tag: str) -> str:
    lower = tag.strip().lower()
    if (
        lower in {"solo", "duo", "group", "no humans", "male focus", "female focus"}
        or _SUBJECT_TAG_RE.match(lower)
    ):
        return "subject"
    if _contains_keyword(lower, _CLOTHING_WORDS):
        return "clothing"
    if _contains_keyword(lower, _APPEARANCE_WORDS):
        return "appearance"
    if _contains_keyword(lower, _ACTION_WORDS):
        return "action"
    if _contains_keyword(lower, _COMPOSITION_WORDS):
        return "composition"
    if _contains_keyword(lower, _SCENE_WORDS):
        return "scene"
    if _contains_keyword(lower, _STYLE_WORDS):
        return "style"
    return "other"


def _is_training_noise_tag(tag: str, user_exclusions: set[str] | None = None) -> bool:
    lower = tag.strip().lower()
    if not lower:
        return True
    if user_exclusions and lower in user_exclusions:
        return True
    return lower in _TRAINING_NOISE_TAGS or any(
        lower.startswith(prefix) for prefix in _TRAINING_NOISE_PREFIXES
    )


def _remove_count_conflicts(tags: list[str], preferred_tags: list[str]) -> tuple[list[str], list[str]]:
    """Resolve only unambiguous person-count conflicts; keep all other details."""
    warnings: list[str] = []
    preferred_by_kind: dict[str, str] = {}
    for tag in preferred_tags:
        match = _COUNT_CONFLICT_RE.match(tag)
        if match and match.group("kind") not in preferred_by_kind:
            preferred_by_kind[match.group("kind")] = tag

    seen_by_kind: dict[str, str] = {}
    output: list[str] = []
    for tag in tags:
        match = _COUNT_CONFLICT_RE.match(tag)
        if not match:
            output.append(tag)
            continue
        kind = match.group("kind")
        selected = preferred_by_kind.get(kind, seen_by_kind.get(kind, tag))
        seen_by_kind.setdefault(kind, selected)
        if tag != selected:
            warnings.append(f"removed count conflict: {tag} (kept {selected})")
            continue
        output.append(tag)
    return _unique(output), _unique(warnings)


def _per_image_strings(value: Any) -> list[str]:
    return _flatten_strings(value)


def _value_at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _category_map(tags: Iterable[str]) -> dict[str, list[str]]:
    result = {key: [] for key in _TRAINING_CATEGORY_ORDER}
    for tag in _unique(tags):
        result[_training_tag_category(tag)].append(tag)
    return result


def _signature_diversity(records: list[dict[str, Any]], category: str) -> float:
    if not records:
        return 0.0
    signatures = {
        tuple(record.get("fused", {}).get("categories", {}).get(category, []))
        for record in records
    }
    return min(1.0, len(signatures) / max(1, len(records)))


def _top_prevalence(records: list[dict[str, Any]], category: str) -> float:
    if not records:
        return 0.0
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(set(record.get("fused", {}).get("categories", {}).get(category, [])))
    return (counts.most_common(1)[0][1] / len(records)) if counts else 0.0


def _character_tag_consistency(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    counts: Counter[str] = Counter()
    for record in records:
        identity_tags = _unique(
            [
                *record.get("wd", {}).get("character", []),
                *record.get("cl", {}).get("character", []),
            ]
        )
        counts.update(set(identity_tags))
    return (counts.most_common(1)[0][1] / len(records)) if counts else 0.0


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_prompt_batch(value: Any, *, max_batch: int = 8) -> list[str]:
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError as exc:
        raise ValueError(f"prompts_json must be a JSON string array: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("prompts_json must be a JSON string array")
    prompts = [str(item).strip() for item in parsed]
    if not prompts or any(not item for item in prompts):
        raise ValueError("prompt batch must contain 1 or more non-empty strings")
    if len(prompts) > max_batch:
        raise ValueError(f"prompt batch size {len(prompts)} exceeds {max_batch}")
    return prompts


def _pad_and_cat_tensors(values: list[Any], torch_module: Any) -> Any:
    if not values:
        raise ValueError("cannot batch an empty tensor list")
    ranks = {int(value.ndim) for value in values}
    if len(ranks) != 1:
        raise ValueError("conditioning tensors have different ranks")
    rank = ranks.pop()
    if rank == 0:
        return torch_module.stack(values, dim=0)
    if rank == 1:
        max_tokens = max(int(value.shape[0]) for value in values)
        padded_vectors: list[Any] = []
        for value in values:
            if int(value.shape[0]) == max_tokens:
                padded_vectors.append(value)
                continue
            expanded = value.new_zeros([max_tokens])
            expanded[: int(value.shape[0])] = value
            padded_vectors.append(expanded)
        return torch_module.stack(padded_vectors, dim=0)

    tail_shapes = {tuple(int(size) for size in value.shape[2:]) for value in values}
    if len(tail_shapes) != 1:
        raise ValueError("conditioning tensor feature dimensions do not match")
    max_tokens = max(int(value.shape[1]) for value in values)
    padded: list[Any] = []
    for value in values:
        if int(value.shape[1]) == max_tokens:
            padded.append(value)
            continue
        target_shape = [int(value.shape[0]), max_tokens, *map(int, value.shape[2:])]
        expanded = value.new_zeros(target_shape)
        slices = [slice(None), slice(0, int(value.shape[1]))]
        slices.extend(slice(None) for _ in value.shape[2:])
        expanded[tuple(slices)] = value
        padded.append(expanded)
    return torch_module.cat(padded, dim=0)


def _merge_prompt_conditioning(encoded: list[Any]) -> list[Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - ComfyUI always provides torch
        raise RuntimeError("AnimaPromptBatchEncode requires ComfyUI's torch runtime") from exc

    if not encoded or any(not isinstance(item, (list, tuple)) for item in encoded):
        raise ValueError("CLIP returned an invalid conditioning structure")
    entry_counts = {len(item) for item in encoded}
    if len(entry_counts) != 1:
        raise ValueError("prompts produced different conditioning schedules")

    output: list[Any] = []
    for entry_index in range(next(iter(entry_counts))):
        entries = [item[entry_index] for item in encoded]
        if any(not isinstance(entry, (list, tuple)) or len(entry) != 2 for entry in entries):
            raise ValueError("CLIP returned an unsupported conditioning entry")
        tensors = [entry[0] for entry in entries]
        metadata = [entry[1] for entry in entries]
        if any(not isinstance(item, dict) for item in metadata):
            raise ValueError("CLIP conditioning metadata must be dictionaries")

        combined_meta: dict[str, Any] = {}
        keys = set(metadata[0])
        if any(set(item) != keys for item in metadata[1:]):
            raise ValueError("prompts produced different conditioning metadata keys")
        for key in keys:
            values = [item[key] for item in metadata]
            if all(torch.is_tensor(value) for value in values):
                combined_meta[key] = _pad_and_cat_tensors(values, torch)
            else:
                first = values[0]
                try:
                    equal = all(value == first for value in values[1:])
                except Exception:
                    equal = False
                if not equal:
                    raise ValueError(
                        f"conditioning metadata {key!r} differs between prompts"
                    )
                combined_meta[key] = first
        output.append([_pad_and_cat_tensors(tensors, torch), combined_meta])
    return output


def install_anima_batch_conditioning_compat() -> bool:
    """Teach ComfyUI's Anima adapter to accept batched T5 token metadata.

    ComfyUI 0.21.1 assumes ``t5xxl_ids`` and ``t5xxl_weights`` are one-
    dimensional and always adds a batch dimension.  ``AnimaPromptBatchEncode``
    already emits ``[batch, tokens]`` metadata, so the unconditional unsqueeze
    turns it into ``[1, batch, tokens]`` and breaks rotary attention.  Preserve
    the upstream implementation for ordinary single-prompt conditioning and
    only replace the batched path.
    """

    try:
        import torch
        import comfy.conds as comfy_conds
        import comfy.model_base as model_base
    except ImportError:
        return False

    anima_class = getattr(model_base, "Anima", None)
    if anima_class is None:
        return False

    original = anima_class.extra_conds
    if bool(getattr(original, "_astr_auto_anima_batch_compat", False)):
        return True

    base_extra_conds = anima_class.__mro__[1].extra_conds

    def extra_conds_with_batch_support(self, **kwargs):
        token_ids = kwargs.get("t5xxl_ids")
        token_rank = int(getattr(token_ids, "ndim", 0)) if token_ids is not None else 0
        if token_ids is None or token_rank <= 1:
            return original(self, **kwargs)
        if token_rank != 2:
            raise RuntimeError(
                "AstrAutoAnima batch conditioning expected t5xxl_ids with "
                f"rank 2, got rank {token_rank}."
            )

        cross_attn = kwargs.get("cross_attn")
        if cross_attn is None:
            return original(self, **kwargs)
        if int(cross_attn.shape[0]) != int(token_ids.shape[0]):
            raise RuntimeError(
                "AstrAutoAnima batch conditioning has different prompt and "
                f"token batch sizes: {cross_attn.shape[0]} != {token_ids.shape[0]}."
            )

        out = base_extra_conds(self, **kwargs)
        token_weights = kwargs.get("t5xxl_weights")
        device = kwargs["device"]

        if token_weights is not None:
            weight_rank = int(getattr(token_weights, "ndim", 0))
            if weight_rank == 1:
                token_weights = token_weights.unsqueeze(0).unsqueeze(-1)
            elif weight_rank == 2:
                token_weights = token_weights.unsqueeze(-1)
            elif weight_rank != 3:
                raise RuntimeError(
                    "AstrAutoAnima batch conditioning expected t5xxl_weights "
                    f"with rank 1, 2, or 3, got rank {weight_rank}."
                )

        if torch.is_inference_mode_enabled():
            inference_dtype = self.get_dtype_inference()
            prepared_weights = (
                token_weights.to(device=device, dtype=inference_dtype)
                if token_weights is not None
                else None
            )
            cross_attn = self.diffusion_model.preprocess_text_embeds(
                cross_attn.to(device=device, dtype=inference_dtype),
                token_ids.to(device=device),
                t5xxl_weights=prepared_weights,
            )
        else:
            out["t5xxl_ids"] = comfy_conds.CONDRegular(token_ids)
            if token_weights is not None:
                out["t5xxl_weights"] = comfy_conds.CONDRegular(token_weights)

        out["c_crossattn"] = comfy_conds.CONDRegular(cross_attn)
        return out

    extra_conds_with_batch_support._astr_auto_anima_batch_compat = True
    extra_conds_with_batch_support._astr_auto_anima_original = original
    anima_class.extra_conds = extra_conds_with_batch_support
    return True


class AnimaPromptBatchEncode:
    CATEGORY = "AstrAutoAnima/Generation"
    FUNCTION = "encode"
    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP", {"forceInput": True}),
                "prompts_json": (
                    "STRING",
                    {
                        "default": "[\"1girl, solo\", \"1girl, outdoors\"]",
                        "multiline": True,
                    },
                ),
            }
        }

    def encode(self, clip, prompts_json):
        if not install_anima_batch_conditioning_compat():
            raise RuntimeError(
                "Anima batched conditioning compatibility could not be enabled; "
                "restart ComfyUI after installing the complete workflow tools package."
            )
        prompts = _parse_prompt_batch(prompts_json)
        encoded = [
            clip.encode_from_tokens_scheduled(clip.tokenize(prompt))
            for prompt in prompts
        ]
        return (_merge_prompt_conditioning(encoded),)


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _unique(str(item) for item in value if item is not None)
    if isinstance(value, str):
        return _split_tags(value)
    return []


def _categorize_tags(tags: Iterable[str]) -> dict[str, list[str]]:
    result = {
        "scene": [],
        "action": [],
        "character": [],
        "appearance": [],
        "special_features": [],
        "clothing": [],
        "composition": [],
        "other": [],
    }
    for tag in _unique(tags):
        if _is_drop_tag(tag):
            continue
        if tag.startswith("character:"):
            result["character"].append(tag.removeprefix("character:").strip())
        elif _contains_keyword(tag, _ACTION_WORDS):
            result["action"].append(tag)
        elif _contains_keyword(tag, _COMPOSITION_WORDS):
            result["composition"].append(tag)
        elif _contains_keyword(tag, _SCENE_WORDS):
            result["scene"].append(tag)
        elif _contains_keyword(tag, _CLOTHING_WORDS):
            result["clothing"].append(tag)
        elif _contains_keyword(tag, _SPECIAL_FEATURE_WORDS):
            result["special_features"].append(tag)
        elif _contains_keyword(tag, _APPEARANCE_WORDS):
            result["appearance"].append(tag)
        else:
            result["other"].append(tag)
    return result


def _safety_level(tags: Iterable[str], ratings: Iterable[str], joy: dict[str, Any]) -> tuple[str, list[str]]:
    combined = " | ".join([*_unique(tags), *_unique(ratings), json.dumps(joy, ensure_ascii=False)]).lower()
    sexual_hits = sorted(marker for marker in _SEXUAL_MARKERS if marker in combined)
    if sexual_hits:
        return "sexual", sexual_hits
    nsfw_hits = sorted(marker for marker in _NSFW_MARKERS if marker in combined)
    if nsfw_hits:
        return "nsfw", nsfw_hits
    if "explicit" in combined:
        return "nsfw", ["tagger rating: explicit"]
    return "normal", []


class AnimaCaptionBatchGuard:
    CATEGORY = "AstrAutoAnima/Training"
    FUNCTION = "guard"
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("validated_caption_list", "qa_log", "passed")
    OUTPUT_IS_LIST = (True, False, False)
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "caption_list": ("STRING", {"forceInput": True}),
                "image_records": ("IMAGE_RECORDS", {"forceInput": True}),
                "min_tags": ("INT", {"default": 5, "min": 0, "max": 500}),
                "max_tags": ("INT", {"default": 80, "min": 1, "max": 1000}),
                "max_duplicate_ratio": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.01}),
                "stop_on_error": ("BOOLEAN", {"default": True}),
            }
        }

    def guard(self, caption_list, image_records, min_tags, max_tags, max_duplicate_ratio, stop_on_error):
        captions = _flatten_strings(caption_list)
        record_count = _count_records(image_records)
        min_count = int(_first(min_tags, 5))
        max_count = int(_first(max_tags, 80))
        max_dup = float(_first(max_duplicate_ratio, 0.35))
        should_stop = bool(_first(stop_on_error, True))

        errors: list[str] = []
        warnings: list[str] = []
        if record_count and len(captions) != record_count:
            errors.append(f"caption/image count mismatch: captions={len(captions)}, images={record_count}")
        if not captions:
            errors.append("caption list is empty")

        tag_counts: list[int] = []
        for index, caption in enumerate(captions):
            lowered = caption.lower()
            if not caption.strip():
                errors.append(f"caption[{index}] is empty")
                continue
            markers = [marker for marker in _CONTROL_MARKERS if marker in lowered]
            if markers:
                errors.append(f"caption[{index}] contains control markers: {markers}")
            split = _split_tags(caption)
            count = len(split)
            tag_counts.append(count)
            if count < min_count:
                errors.append(f"caption[{index}] has too few tags: {count} < {min_count}")
            if count > max_count:
                errors.append(f"caption[{index}] has too many tags: {count} > {max_count}")
            repeated = count - len(set(split))
            if repeated:
                errors.append(f"caption[{index}] contains {repeated} repeated tags")

        duplicate_ratio = 0.0
        if captions:
            counts = Counter(captions)
            duplicate_items = sum(count - 1 for count in counts.values() if count > 1)
            duplicate_ratio = duplicate_items / len(captions)
            if duplicate_ratio > max_dup:
                errors.append(f"duplicate caption ratio too high: {duplicate_ratio:.3f} > {max_dup:.3f}")

        passed = not errors
        report = {
            "passed": passed,
            "caption_count": len(captions),
            "image_record_count": record_count,
            "duplicate_ratio": round(duplicate_ratio, 6),
            "min_observed_tags": min(tag_counts) if tag_counts else 0,
            "max_observed_tags": max(tag_counts) if tag_counts else 0,
            "policy": "tag count limits and repeated tags are blocking errors",
            "errors": errors,
            "warnings": warnings,
        }
        qa_log = json.dumps(report, ensure_ascii=False, indent=2)
        if errors and should_stop:
            raise ValueError(f"Anima caption batch QA failed:\n{qa_log}")
        return captions, qa_log, passed


class AnimaImageBatchChunker:
    """Expose one loaded IMAGE batch as a list of bounded inference batches."""

    CATEGORY = "AstrAutoAnima/Training"
    FUNCTION = "chunk"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image_chunks", "chunk_log")
    OUTPUT_IS_LIST = (True, False)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"forceInput": True}),
                "chunk_size": ("INT", {"default": 64, "min": 1, "max": 256}),
            }
        }

    def chunk(self, image, chunk_size):
        size = int(chunk_size)
        try:
            image_count = int(image.shape[0])
        except (AttributeError, IndexError, TypeError) as exc:
            raise ValueError("AnimaImageBatchChunker expects an IMAGE batch with a batch dimension") from exc
        if image_count <= 0:
            raise ValueError("AnimaImageBatchChunker received an empty IMAGE batch")

        chunks = [image[start : start + size] for start in range(0, image_count, size)]
        report = {
            "image_count": image_count,
            "chunk_size": size,
            "chunk_count": len(chunks),
            "chunk_lengths": [int(chunk.shape[0]) for chunk in chunks],
        }
        return chunks, json.dumps(report, ensure_ascii=False, indent=2)


class AnimaTrainingTagFusion:
    """Fuse WD and CL batch outputs without letting the larger CL vocabulary dominate."""

    CATEGORY = "AstrAutoAnima/Training"
    FUNCTION = "fuse"
    RETURN_TYPES = ("TRAIN_RECORDS", "STRING")
    RETURN_NAMES = ("train_records", "fusion_log")
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wd_general": ("STRING", {"forceInput": True}),
                "wd_rating": ("STRING", {"forceInput": True}),
                "wd_character": ("STRING", {"forceInput": True}),
                "cl_general": ("STRING", {"forceInput": True}),
                "cl_rating": ("STRING", {"forceInput": True}),
                "cl_character": ("STRING", {"forceInput": True}),
                "image_records": ("IMAGE_RECORDS", {"forceInput": True}),
                "max_cl_only_tags": ("INT", {"default": 10, "min": 0, "max": 100}),
                "exclude_tags": (
                    "STRING",
                    {
                        "default": "watermark, signature, artist name, username, logo, text, lowres, jpeg artifacts, blurry",
                        "multiline": True,
                    },
                ),
            },
            "optional": {
                "joy_caption": ("STRING", {"forceInput": True}),
            },
        }

    def fuse(
        self,
        wd_general,
        wd_rating,
        wd_character,
        cl_general,
        cl_rating,
        cl_character,
        image_records,
        max_cl_only_tags,
        exclude_tags,
        joy_caption=None,
    ):
        wd_general_values = _per_image_strings(wd_general)
        wd_rating_values = _per_image_strings(wd_rating)
        wd_character_values = _per_image_strings(wd_character)
        cl_general_values = _per_image_strings(cl_general)
        cl_rating_values = _per_image_strings(cl_rating)
        cl_character_values = _per_image_strings(cl_character)
        joy_values = _per_image_strings(joy_caption)
        image_values = _flatten_records(image_records)
        cl_cap = int(_first(max_cl_only_tags, 10))
        user_exclusions = set(_split_tags(exclude_tags))

        counts = [
            len(wd_general_values),
            len(wd_rating_values),
            len(wd_character_values),
            len(cl_general_values),
            len(cl_rating_values),
            len(cl_character_values),
            len(image_values),
        ]
        record_count = max(counts) if counts else 0
        records: list[dict[str, Any]] = []
        total_cl_kept = 0
        total_cl_dropped = 0
        total_warnings = 0

        for index in range(record_count):
            wd_tags = [
                tag
                for tag in _split_tags(_value_at(wd_general_values, index))
                if not _is_training_noise_tag(tag, user_exclusions)
            ]
            cl_tags = [
                tag
                for tag in _split_tags(_value_at(cl_general_values, index))
                if not _is_training_noise_tag(tag, user_exclusions)
            ]
            wd_tags = _unique(wd_tags)
            cl_tags = _unique(cl_tags)
            wd_set = set(wd_tags)
            cl_set = set(cl_tags)

            consensus = [tag for tag in wd_tags if tag in cl_set]
            wd_only = [tag for tag in wd_tags if tag not in cl_set]
            cl_only_all = [tag for tag in cl_tags if tag not in wd_set]
            cl_only = cl_only_all[:cl_cap]
            total_cl_kept += len(cl_only)
            total_cl_dropped += max(0, len(cl_only_all) - len(cl_only))

            joy_text = _value_at(joy_values, index)
            joy = _extract_json_object(joy_text) if joy_text else {}
            semantic_extra: list[str] = []
            for key in ("scene", "action", "relation", "appearance", "clothing", "composition"):
                semantic_extra.extend(_json_list(joy.get(key)))
            semantic_extra = [
                tag
                for tag in _unique(semantic_extra)
                if not _is_training_noise_tag(tag, user_exclusions)
            ]

            candidate_tags = _unique([*consensus, *wd_only, *cl_only, *semantic_extra])
            candidate_tags, warnings = _remove_count_conflicts(candidate_tags, wd_tags)
            if len(cl_only_all) > cl_cap:
                warnings.append(
                    f"limited CL-only tags: kept={cl_cap}, dropped={len(cl_only_all) - cl_cap}"
                )
            total_warnings += len(warnings)

            categories = _category_map(candidate_tags)
            for relation in _json_list(joy.get("relation")):
                relation = relation.strip().lower()
                if relation and relation not in categories["relation"]:
                    categories["relation"].append(relation)

            image_record = image_values[index] if index < len(image_values) else {"index": index}
            records.append(
                {
                    "index": index,
                    "image": image_record,
                    "wd": {
                        "general": wd_tags,
                        "character": _split_tags(_value_at(wd_character_values, index)),
                        "rating": _split_tags(_value_at(wd_rating_values, index)),
                    },
                    "cl": {
                        "general": cl_tags,
                        "character": _split_tags(_value_at(cl_character_values, index)),
                        "rating": _split_tags(_value_at(cl_rating_values, index)),
                    },
                    "joy": {
                        **joy,
                        "raw": joy_text,
                        "json_valid": bool(joy),
                    },
                    "fused": {
                        "consensus_tags": consensus,
                        "wd_only": wd_only,
                        "cl_only": cl_only,
                        "cl_only_dropped": cl_only_all[cl_cap:],
                        "semantic_extra": semantic_extra,
                        "candidate_tags": candidate_tags,
                        "categories": categories,
                        "warnings": _unique(warnings),
                    },
                }
            )

        mismatched_inputs = {
            "wd_general": len(wd_general_values),
            "cl_general": len(cl_general_values),
            "image_records": len(image_values),
        }
        report = {
            "schema_version": "1.0",
            "records": len(records),
            "input_lengths": mismatched_inputs,
            "aligned": len(set(mismatched_inputs.values())) <= 1,
            "max_cl_only_tags": cl_cap,
            "cl_only_kept": total_cl_kept,
            "cl_only_dropped": total_cl_dropped,
            "warnings": total_warnings,
            "joy_records": sum(1 for record in records if record["joy"]["json_valid"]),
        }
        return records, json.dumps(report, ensure_ascii=False, indent=2)


class AnimaDatasetTypeResolver:
    """Resolve the dataset-level LoRA target, with manual choice always taking priority."""

    CATEGORY = "AstrAutoAnima/Training"
    FUNCTION = "resolve"
    RETURN_TYPES = ("TRAIN_RECORDS", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("train_records", "resolved_train_type", "type_scores_json", "type_report")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "train_records": ("TRAIN_RECORDS", {"forceInput": True}),
                "train_type_mode": (
                    ["AUTO", "CHARACTER", "STYLE", "CLOTHING"],
                    {"default": "AUTO"},
                ),
                "auto_accept_min_score": (
                    "FLOAT",
                    {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "auto_accept_margin": (
                    "FLOAT",
                    {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
            }
        }

    def resolve(self, train_records, train_type_mode, auto_accept_min_score, auto_accept_margin):
        records = _flatten_records(train_records)
        selected_mode = str(train_type_mode).upper()
        min_score = float(auto_accept_min_score)
        margin = float(auto_accept_margin)

        identity_consistency = _character_tag_consistency(records)
        appearance_stability = _top_prevalence(records, "appearance")
        clothing_stability = _top_prevalence(records, "clothing")
        style_tag_stability = _top_prevalence(records, "style")
        content_variation = (
            _signature_diversity(records, "action")
            + _signature_diversity(records, "scene")
            + _signature_diversity(records, "clothing")
        ) / 3.0
        subject_variation = (
            _signature_diversity(records, "subject")
            + _signature_diversity(records, "appearance")
            + _signature_diversity(records, "clothing")
        ) / 3.0
        identity_variation = max(
            _signature_diversity(records, "appearance"),
            1.0 - identity_consistency if identity_consistency else 0.0,
        )

        joy_style_notes: list[str] = []
        for record in records:
            joy_style_notes.extend(_json_list(record.get("joy", {}).get("style_notes")))
        joy_style_consistency = 0.0
        if records and joy_style_notes:
            counts = Counter(joy_style_notes)
            joy_style_consistency = counts.most_common(1)[0][1] / len(records)

        character_score = min(
            1.0,
            0.45 * identity_consistency
            + 0.35 * appearance_stability
            + 0.20 * content_variation,
        )
        clothing_score = min(
            1.0,
            0.70 * clothing_stability
            + 0.15 * identity_variation
            + 0.15 * content_variation,
        )
        if joy_style_consistency:
            style_score = min(1.0, 0.65 * joy_style_consistency + 0.35 * subject_variation)
        else:
            # WD/CL do not provide enough evidence to auto-confirm a style dataset.
            style_score = min(0.60, 0.35 * subject_variation + 0.25 * style_tag_stability)

        scores = {
            "CHARACTER": round(character_score, 6),
            "STYLE": round(style_score, 6),
            "CLOTHING": round(clothing_score, 6),
        }
        ranking = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        if selected_mode != "AUTO":
            resolved = selected_mode
            confidence = 1.0
            decision = "manual override"
        elif not records:
            resolved = "AMBIGUOUS"
            confidence = 0.0
            decision = "no records"
        else:
            top_type, top_score = ranking[0]
            second_score = ranking[1][1]
            confidence = top_score
            if top_score >= min_score and top_score - second_score >= margin:
                resolved = top_type
                decision = "auto accepted"
            else:
                resolved = "AMBIGUOUS"
                decision = "auto confidence gate rejected"

        evidence = {
            "record_count": len(records),
            "identity_consistency": round(identity_consistency, 6),
            "appearance_stability": round(appearance_stability, 6),
            "clothing_stability": round(clothing_stability, 6),
            "style_tag_stability": round(style_tag_stability, 6),
            "joy_style_consistency": round(joy_style_consistency, 6),
            "content_variation": round(content_variation, 6),
            "subject_variation": round(subject_variation, 6),
        }
        report = {
            "selected_mode": selected_mode,
            "resolved_train_type": resolved,
            "confidence": round(confidence, 6),
            "decision": decision,
            "auto_accept_min_score": min_score,
            "auto_accept_margin": margin,
            "scores": scores,
            "evidence": evidence,
            "warning": (
                "AUTO could not distinguish the target; select CHARACTER, STYLE, or CLOTHING manually."
                if resolved == "AMBIGUOUS"
                else ""
            ),
        }
        return records, resolved, json.dumps(scores, ensure_ascii=False, indent=2), json.dumps(
            report, ensure_ascii=False, indent=2
        )


class AnimaTrainingCaptionCompiler:
    """Compile captions according to what the trigger is supposed to learn."""

    CATEGORY = "AstrAutoAnima/Training"
    FUNCTION = "compile"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("caption_list", "compiler_report")
    OUTPUT_IS_LIST = (True, False)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "train_records": ("TRAIN_RECORDS", {"forceInput": True}),
                "resolved_train_type": ("STRING", {"forceInput": True}),
                "trigger_word_override": ("STRING", {"default": ""}),
                "character_outfit_policy": (
                    ["describe", "absorb_default_outfit"],
                    {"default": "describe"},
                ),
                "target_absorption_threshold": (
                    "FLOAT",
                    {"default": 0.85, "min": 0.5, "max": 1.0, "step": 0.01},
                ),
                "max_tags": ("INT", {"default": 0, "min": 0, "max": 200}),
                "include_joy_relations": ("BOOLEAN", {"default": True}),
            }
        }

    def compile(
        self,
        train_records,
        resolved_train_type,
        trigger_word_override,
        character_outfit_policy,
        target_absorption_threshold,
        max_tags,
        include_joy_relations,
    ):
        records = _flatten_records(train_records)
        train_type = str(resolved_train_type).upper()
        if train_type not in {"CHARACTER", "STYLE", "CLOTHING"}:
            raise ValueError(
                "Training type is AMBIGUOUS. Select CHARACTER, STYLE, or CLOTHING in AnimaDatasetTypeResolver."
            )

        threshold = float(target_absorption_threshold)
        outfit_policy = str(character_outfit_policy)
        trigger = re.sub(r"\s+", " ", str(trigger_word_override).strip())
        explicit_max = int(max_tags)
        type_caps = {"CHARACTER": 40, "STYLE": 60, "CLOTHING": 50}
        tag_cap = explicit_max if explicit_max > 0 else type_caps[train_type]
        use_relations = bool(include_joy_relations)

        frequencies: Counter[str] = Counter()
        for record in records:
            frequencies.update(set(record.get("fused", {}).get("candidate_tags", [])))
        stable_tags = {
            tag for tag, count in frequencies.items() if records and count / len(records) >= threshold
        }

        absorb_categories: set[str]
        if train_type == "CHARACTER":
            absorb_categories = {"appearance"}
            if outfit_policy == "absorb_default_outfit":
                absorb_categories.add("clothing")
        elif train_type == "CLOTHING":
            absorb_categories = {"clothing"}
        else:
            absorb_categories = {"style"}

        captions: list[str] = []
        absorbed_counter: Counter[str] = Counter()
        truncated = 0
        for record in records:
            categories = record.get("fused", {}).get("categories", {})
            ordered: list[str] = []
            for category in _TRAINING_CATEGORY_ORDER:
                if category == "relation" and not use_relations:
                    continue
                for tag in categories.get(category, []):
                    if tag in stable_tags and category in absorb_categories:
                        absorbed_counter[tag] += 1
                        continue
                    if not _is_training_noise_tag(tag):
                        ordered.append(tag)
            ordered = _unique(ordered)
            if len(ordered) > tag_cap:
                ordered = ordered[:tag_cap]
                truncated += 1
            caption_parts = ([trigger] if trigger else []) + ordered
            captions.append(", ".join(caption_parts))

        report = {
            "schema_version": "1.0",
            "resolved_train_type": train_type,
            "record_count": len(records),
            "trigger_word_override": trigger,
            "trigger_note": (
                "Compiler inserted the override as token 1."
                if trigger
                else "No override inserted; downstream AnimaCaptionPrepare should prepend the folder name."
            ),
            "character_outfit_policy": outfit_policy,
            "target_absorption_threshold": threshold,
            "absorbed_categories": sorted(absorb_categories),
            "absorbed_tags": [tag for tag, _ in absorbed_counter.most_common()],
            "max_tags": tag_cap,
            "truncated_caption_count": truncated,
            "include_joy_relations": use_relations,
        }
        return captions, json.dumps(report, ensure_ascii=False, indent=2)


class AnimaReverseCompiler:
    CATEGORY = "AstrAutoAnima/Reverse"
    FUNCTION = "compile"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("anima_prompt", "structured_json", "safety_level", "summary")
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wd_tags": ("STRING", {"forceInput": True}),
                "wd_general": ("STRING", {"forceInput": True}),
                "wd_rating": ("STRING", {"forceInput": True}),
                "wd_character": ("STRING", {"forceInput": True}),
                "ct_tags": ("STRING", {"forceInput": True}),
                "ct_general": ("STRING", {"forceInput": True}),
                "ct_rating": ("STRING", {"forceInput": True}),
                "ct_character": ("STRING", {"forceInput": True}),
                "joy_caption": ("STRING", {"forceInput": True}),
                "preset": (["full", "scene", "action", "character", "safe", "raw", "custom"], {"default": "full"}),
                "include_scene": ("BOOLEAN", {"default": True}),
                "include_action": ("BOOLEAN", {"default": True}),
                "include_character": ("BOOLEAN", {"default": True}),
                "include_appearance": ("BOOLEAN", {"default": True}),
                "include_special_features": ("BOOLEAN", {"default": True}),
                "include_clothing": ("BOOLEAN", {"default": True}),
                "include_composition": ("BOOLEAN", {"default": True}),
                "include_other": ("BOOLEAN", {"default": True}),
                "include_safety": ("BOOLEAN", {"default": True}),
            }
        }

    def compile(
        self,
        wd_tags,
        wd_general,
        wd_rating,
        wd_character,
        ct_tags,
        ct_general,
        ct_rating,
        ct_character,
        joy_caption,
        preset,
        include_scene,
        include_action,
        include_character,
        include_appearance,
        include_special_features,
        include_clothing,
        include_composition,
        include_other,
        include_safety,
    ):
        selected_preset = str(_first(preset, "full"))
        wd = {
            "tags": _split_tags(wd_tags),
            "general": _split_tags(wd_general),
            "rating": _flatten_strings(wd_rating),
            "character": _split_tags(wd_character),
        }
        ct = {
            "tags": _split_tags(ct_tags),
            "general": _split_tags(ct_general),
            "rating": _flatten_strings(ct_rating),
            "character": _split_tags(ct_character),
        }
        joy_text = "\n".join(_flatten_strings(joy_caption))
        joy = _extract_json_object(joy_text)

        categorized = _categorize_tags([*wd["general"], *ct["general"]])
        categorized["character"] = _unique([*wd["character"], *ct["character"], *categorized["character"]])
        for key in ("scene", "action", "character", "appearance", "special_features", "clothing", "composition", "other"):
            categorized[key] = _unique([*categorized[key], *_json_list(joy.get(key))])

        all_tags = _unique([*wd["tags"], *ct["tags"], *sum(categorized.values(), [])])
        safety, safety_reasons = _safety_level(all_tags, [*wd["rating"], *ct["rating"]], joy)

        enabled = {
            "scene": bool(_first(include_scene, True)),
            "action": bool(_first(include_action, True)),
            "character": bool(_first(include_character, True)),
            "appearance": bool(_first(include_appearance, True)),
            "special_features": bool(_first(include_special_features, True)),
            "clothing": bool(_first(include_clothing, True)),
            "composition": bool(_first(include_composition, True)),
            "other": bool(_first(include_other, True)),
            "safety": bool(_first(include_safety, True)),
        }
        if selected_preset == "scene":
            enabled.update(action=False, character=False, appearance=False, special_features=False, clothing=False, other=False)
        elif selected_preset == "action":
            enabled.update(scene=False, character=False, appearance=False, special_features=False, clothing=False, other=False)
        elif selected_preset == "character":
            enabled.update(scene=False, action=False, composition=False, other=False)
        elif selected_preset == "raw":
            enabled.update(scene=False, action=False, character=False, appearance=False, special_features=False, clothing=False, composition=False, other=False)

        if selected_preset == "safe" or (
            selected_preset == "custom" and enabled["safety"]
        ):
            blocked = _SEXUAL_MARKERS | _NSFW_MARKERS
            for key, values in categorized.items():
                categorized[key] = [tag for tag in values if not _contains_keyword(tag, blocked)]

        order = ["character", "appearance", "special_features", "clothing", "action", "composition", "scene", "other"]
        prompt_parts: list[str] = []
        if selected_preset == "raw":
            # Raw mode bypasses category selection, but still normalizes,
            # deduplicates, and removes non-content quality/model metadata.
            # Previously every category was disabled without adding a raw
            # fallback, which produced an empty generation prompt.
            prompt_parts.extend(all_tags)
        else:
            for key in order:
                if enabled.get(key, False):
                    prompt_parts.extend(categorized[key])
        anima_prompt = ", ".join(_unique(tag for tag in prompt_parts if not _is_drop_tag(tag)))

        structured = {
            "schema_version": "1.0",
            "compiler": "AnimaReverseCompiler",
            "preset": selected_preset,
            "enabled": enabled,
            "raw": {
                "wd": wd,
                "ct": ct,
                "joycaption": joy_text,
                "joycaption_json_valid": bool(joy),
            },
            "compiled": {
                **categorized,
                "safety": {
                    "level": safety,
                    "reasons": safety_reasons,
                    "wd_rating": wd["rating"],
                    "ct_rating": ct["rating"],
                },
                "anima_prompt": anima_prompt,
            },
        }
        structured_json = json.dumps(structured, ensure_ascii=False, indent=2)
        summary = (
            f"preset={selected_preset}; safety={safety}; prompt_tags={len(_split_tags(anima_prompt))}; "
            f"wd_tags={len(wd['tags'])}; ct_tags={len(ct['tags'])}; joy_json={bool(joy)}"
        )
        return anima_prompt, structured_json, safety, summary


class AnimaReverseResultSaver:
    CATEGORY = "AstrAutoAnima/Reverse"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("record_path", "reverse_id", "structured_json")
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"forceInput": True}),
                "structured_json": ("STRING", {"forceInput": True}),
                "anima_prompt": ("STRING", {"forceInput": True}),
                "storage_root": ("STRING", {"default": "/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge/reverse_history"}),
                "qq_user_id": ("STRING", {"default": ""}),
                "session_type": (["unknown", "private", "group"], {"default": "unknown"}),
                "session_id": ("STRING", {"default": ""}),
                "role_preset": ("STRING", {"default": ""}),
                "style_preset": ("STRING", {"default": ""}),
                "save_thumbnail": ("BOOLEAN", {"default": False}),
            }
        }

    def save(
        self,
        image,
        structured_json,
        anima_prompt,
        storage_root,
        qq_user_id,
        session_type,
        session_id,
        role_preset,
        style_preset,
        save_thumbnail,
    ):
        root = Path(str(storage_root)).expanduser().resolve()
        workspace = Path("/workspace").resolve()
        try:
            root.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"storage_root must stay under /workspace: {root}") from exc

        tensor = image[0].detach().cpu().numpy() if hasattr(image[0], "detach") else np.asarray(image[0])
        array = np.clip(tensor * 255.0, 0, 255).astype(np.uint8)
        image_hash = hashlib.sha256(array.tobytes()).hexdigest()

        now = datetime.now(timezone.utc)
        reverse_id = f"{now.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"
        records_dir = root / "records" / now.strftime("%Y") / now.strftime("%m")
        index_dir = root / "index"
        records_dir.mkdir(parents=True, exist_ok=True)
        index_dir.mkdir(parents=True, exist_ok=True)

        try:
            record = json.loads(str(structured_json))
            if not isinstance(record, dict):
                record = {"compiler_output": record}
        except json.JSONDecodeError:
            record = {"compiler_output_raw": str(structured_json)}

        record.update(
            {
                "reverse_id": reverse_id,
                "created_at": now.isoformat(),
                "image_sha256": image_hash,
                "source": {
                    "qq_user_id": str(qq_user_id),
                    "session_type": str(session_type),
                    "session_id": str(session_id),
                },
                "selection": {
                    "role_preset": str(role_preset) or None,
                    "style_preset": str(style_preset) or None,
                },
                "actual_generation_prompt": str(anima_prompt),
                "user_correction": None,
                "pool_state": "pending_review",
            }
        )

        if bool(save_thumbnail):
            thumbnail_dir = root / "thumbnails"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail = Image.fromarray(array)
            thumbnail.thumbnail((512, 512), Image.Resampling.LANCZOS)
            thumbnail_path = thumbnail_dir / f"rev_{reverse_id}.webp"
            thumbnail.save(thumbnail_path, "WEBP", quality=85)
            record["thumbnail_path"] = str(thumbnail_path)

        record_path = records_dir / f"rev_{reverse_id}.json"
        payload = json.dumps(record, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=".reverse_", suffix=".tmp", dir=records_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, record_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        index_entry = {
            "reverse_id": reverse_id,
            "created_at": now.isoformat(),
            "image_sha256": image_hash,
            "record_path": str(record_path),
            "safety_level": record.get("compiled", {}).get("safety", {}).get("level", "unknown"),
            "pool_state": "pending_review",
        }
        with (index_dir / "reverse_history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

        return {
            "ui": {
                "text": [str(record_path)],
                "reverse_id": [reverse_id],
                "anima_prompt": [str(anima_prompt)],
                "structured_json": [payload],
                "safety_level": [
                    str(record.get("compiled", {}).get("safety", {}).get("level", "unknown"))
                ],
            },
            "result": (str(record_path), reverse_id, payload),
        }
