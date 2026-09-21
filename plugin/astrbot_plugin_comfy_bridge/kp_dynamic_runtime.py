from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct local tests
    from workflow_runtime import WorkflowError


_STATIC_K_ID = re.compile(r"^kp-[a-z]\d{2}-(?:safe|adult)$", re.IGNORECASE)
_DYNAMIC_K_ID = re.compile(r"^kp-dyn-[nhs]-[0-9a-f]{12}$", re.IGNORECASE)

_SUBJECT_RE = re.compile(
    r"^(?:1woman|1girl|solo|adult woman|\d{2} years old|fully clothed|non-explicit)$",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(
    r"^(?:masterpiece|best quality|highres|high resolution|ultra detailed|"
    r"highly detailed|8k|photorealistic|sharp focus)$",
    re.IGNORECASE,
)
_SEXUAL_RE = re.compile(
    r"\b(?:pussy|vagina|vulva|genitals?|clitoris|penis|cock|dick|testicles?|"
    r"masturbat\w*|fingering|penetrat\w*|intercourse|oral sex|blowjob|handjob|"
    r"deepthroat|cunnilingus|fellatio|anal|vaginal|sex\w*|orgasm\w*|"
    r"cum\w*|semen|ejaculat\w*|creampie|cream pie|fuck\w*|suck\w*|facial|shaft|"
    r"hand job|doggy style|missionary|cowgirl|insertion|thrust\w*|sex toys?|dildos?|vibrators?|urina\w*|pee|peeing|peed|pissing|watersports)\b",
    re.IGNORECASE,
)
_NSFW_RE = re.compile(
    r"\b(?:nude|naked|topless|bottomless|breasts?|boobs?|nipples?|areolae?|"
    r"sideboob|underboob|ass|buttocks?|no bra|no panties|panties|bra|lingerie|"
    r"shirt fully open|bare chest|exposed|see-through|cameltoe|explicit exposure)\b",
    re.IGNORECASE,
)
_UNSAFE_CONTEXT_RE = re.compile(
    r"\b(?:child|children|kid|minor|underage|teen(?:ager)?|schoolgirl|"
    r"loli|shota|unconscious|passed out|drugged|forced|coerc\w*|blackmail|"
    r"non.?consensual|rape|voyeur\w*|peeping|spy camera|hidden camera|protesting|"
    r"unaware|bystanders?|other customers?|public exposure|risk of being watched|caught)\b",
    re.IGNORECASE,
)

_SLOT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "camera",
        re.compile(
            r"\b(?:shot|view|angle|pov|close-up|closeup|wide angle|low angle|"
            r"high angle|eye level|camera|lens|\d{2,3}mm|depth of field|bokeh|"
            r"composition|framing|film still|photo|photography|kodak|fujifilm|"
            r"fuji|leica|arri|panavision|polaroid|cctv|grain)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "lighting",
        re.compile(
            r"\b(?:light|lighting|lit|glow|shadow|sunlight|moonlight|neon|"
            r"golden hour|blue hour|dawn|dusk|sunset|sunrise|backlit|rim light|"
            r"softbox|rembrandt|silhouette|color temperature)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "expression",
        re.compile(
            r"\b(?:expression|smile|smiling|gaze|eyes?|eye contact|looking|"
            r"blush|blushing|mouth|lips?|tears?|crying|laughing|bored|confident|"
            r"shy|embarrassed|playful|serious|surprised|dazed|nervous)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hair_makeup",
        re.compile(
            r"\b(?:hair|hairstyle|ponytail|twintails?|braids?|bun|bangs|makeup|"
            r"foundation|eyeliner|eyeshadow|lipstick|mascara|manicure|nail polish)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "wardrobe",
        re.compile(
            r"\b(?:dress|shirt|blouse|skirt|uniform|kimono|yukata|suit|jacket|"
            r"coat|stockings?|heels?|shoes?|boots?|apron|swimsuit|bikini|robe|"
            r"sweater|hoodie|shorts|pants|jeans|gloves?|scarf|hat|costume|fabric)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "pose",
        re.compile(
            r"\b(?:sitting|standing|kneeling|lying|leaning|walking|running|"
            r"crouching|bending|reclining|stretching|dancing|legs?|arms?|hands?|"
            r"holding|reaching|turning|arching|crossed|on all fours|pose|posture)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prop",
        re.compile(
            r"\b(?:desk|chair|bed|book|phone|umbrella|mirror|bottle|glass|cup|"
            r"microphone|teleprompter|laptop|camera|candle|flower|pet|cat|dog|"
            r"bag|suitcase|pillow|towel|shower|bathtub)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "scene",
        re.compile(
            r"\b(?:room|street|alley|beach|office|studio|bathroom|bedroom|"
            r"kitchen|onsen|train|subway|airport|store|shop|boutique|hotel|"
            r"rooftop|balcony|window|garden|park|pool|restaurant|library|"
            r"hospital|church|cinema|elevator|stairs?|car|bus|festival|shrine)\b",
            re.IGNORECASE,
        ),
    ),
)


def load_kp_module_catalog(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取 KP 动态模块库：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise WorkflowError("KP 动态模块库必须包含 modules 对象。")
    return data


def _tokens(prompt: str) -> list[str]:
    return [" ".join(value.split()) for value in str(prompt).split(",") if value.strip()]


def _safety_for_text(text: str) -> str:
    text = str(text).replace("_", " ")
    if _SEXUAL_RE.search(text):
        return "S"
    if _NSFW_RE.search(text):
        return "H"
    return "N"


def _safety_allows(requested: str, candidate: str) -> bool:
    levels = {"N": 0, "H": 1, "S": 2}
    return levels.get(candidate, 2) <= levels.get(requested, 0)


def _slot_for_token(token: str) -> str:
    if _SEXUAL_RE.search(token) or _NSFW_RE.search(token):
        return "exposure"
    for name, pattern in _SLOT_PATTERNS:
        if pattern.search(token):
            return name
    return "detail"


def _clean_token(token: str, safety_code: str) -> str:
    value = " ".join(str(token).strip(" ,\t\r\n").split())
    if not value or _SUBJECT_RE.fullmatch(value) or _QUALITY_RE.fullmatch(value):
        return ""
    if _UNSAFE_CONTEXT_RE.search(value):
        return ""
    candidate_safety = _safety_for_text(value)
    if not _safety_allows(safety_code, candidate_safety):
        return ""
    return value


def _base_entries(pool: dict[str, Any], safety_code: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in pool.get("prompts", []):
        if not isinstance(item, dict) or not bool(item.get("enabled", True)):
            continue
        prompt_id = str(item.get("id", ""))
        if not _STATIC_K_ID.fullmatch(prompt_id):
            continue
        item_safety = str(item.get("safety_code", "N")).upper()
        if safety_code == "N":
            if item_safety == "N" and _safety_for_text(str(item.get("prompt", ""))) == "N":
                result.append(item)
            continue
        if item_safety != "S":
            continue
        classified = _safety_for_text(str(item.get("prompt", "")))
        if safety_code == classified:
            result.append(item)
    return result


def _pick(items: list[Any]) -> Any:
    if not items:
        return None
    return secrets.choice(items)


def _module_candidates(
    catalog: dict[str, Any], slot: str, safety_code: str
) -> list[dict[str, Any]]:
    raw = catalog.get("modules", {}).get(slot, [])
    if not isinstance(raw, list):
        return []
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and str(item.get("text", "")).strip()
        and _safety_allows(safety_code, str(item.get("safety_code", "N")).upper())
        and not _UNSAFE_CONTEXT_RE.search(str(item.get("text", "")))
    ]


def _choose_requested_safety(safety_codes: list[str] | tuple[str, ...]) -> str:
    available = [code for code in ("N", "H", "S") if code in {str(v).upper() for v in safety_codes}]
    if not available:
        raise WorkflowError("K 动态拼装未收到可用的 N/H/S 级别。")
    return _pick(available)


def _anchor_slots(item: dict[str, Any], safety_code: str) -> dict[str, list[str]]:
    slots: dict[str, list[str]] = {}
    for raw in _tokens(str(item.get("prompt", ""))):
        token = _clean_token(raw, safety_code)
        if not token:
            continue
        slots.setdefault(_slot_for_token(token), []).append(token)
    return slots


def _deduplicate(tokens: list[str], max_tags: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        folded = token.casefold()
        if not token or folded in seen:
            continue
        seen.add(folded)
        result.append(token)
        if len(result) >= max_tags:
            break
    return result


def assemble_dynamic_k_prompt(
    pool: dict[str, Any],
    catalog: dict[str, Any],
    *,
    safety_codes: list[str] | tuple[str, ...],
    preserve_character: bool = False,
    min_optional_modules: int = 4,
    max_optional_modules: int = 7,
    max_tags: int = 72,
) -> dict[str, Any]:
    requested_safety = [
        code
        for code in ("N", "H", "S")
        if code in {str(value).upper() for value in safety_codes}
    ]
    viable = [
        (code, bases)
        for code in requested_safety
        if (bases := _base_entries(pool, code))
    ]
    if not viable:
        labels = ",".join(requested_safety) or "无"
        raise WorkflowError(f"KP 动态拼装没有可用的 {labels} 级别基础场景。")
    safety_code, bases = _pick(viable)

    anchor = dict(_pick(bases))
    anchor_slots = _anchor_slots(anchor, safety_code)
    prefix = ["1woman", "solo", "adult woman", "25 years old"]
    if safety_code == "N":
        prefix.extend(["fully clothed", "non-explicit"])

    tokens = list(prefix)
    components: list[dict[str, str]] = [
        {
            "slot": "anchor",
            "module_id": str(anchor.get("pair_id", anchor.get("id", ""))),
            "text": str(anchor.get("name", "K scene")),
        }
    ]

    # Exactly one module is selected for every structural slot. Replacing the
    # anchor's slot rather than appending multiple donors is the primary
    # contradiction guard (one location, one clothing state, one exposure
    # state and one pose per result). The 00 example is retained as fallback
    # and as a small narrative-detail donor.
    for slot in ("scene", "exposure", "wardrobe", "pose"):
        candidates = _module_candidates(catalog, slot, safety_code)
        if slot == "exposure":
            exact = [
                item
                for item in candidates
                if str(item.get("safety_code", "N")).upper() == safety_code
            ]
            if exact:
                candidates = exact
        module = _pick(candidates)
        module_tokens = []
        if module:
            module_tokens = [
                token
                for token in (
                    _clean_token(value, safety_code)
                    for value in _tokens(str(module.get("text", "")))
                )
                if token
            ][:3]
        if not module_tokens:
            fallback = anchor_slots.get(slot, [])
            if slot == "exposure":
                exact = [token for token in fallback if _safety_for_text(token) == safety_code]
                fallback = exact or fallback
            module_tokens = fallback[:3]
            module = {
                "id": f"anchor:{anchor.get('id', '')}:{slot}",
                "text": ", ".join(module_tokens),
            }
        tokens.extend(module_tokens)
        components.append(
            {
                "slot": slot,
                "module_id": str(module.get("id", "")),
                "text": ", ".join(module_tokens),
            }
        )

    slots = ["camera", "lighting", "expression", "style", "makeup", "detail", "prop"]
    if not preserve_character:
        slots.extend(["hair", "marking", "persona"])
    available_slots = [slot for slot in slots if _module_candidates(catalog, slot, safety_code)]
    if not available_slots:
        raise WorkflowError("KP 动态模块库没有与当前安全级别兼容的模块。")

    low = max(1, min(int(min_optional_modules), len(available_slots)))
    high = max(low, min(int(max_optional_modules), len(available_slots)))
    module_count = low + secrets.randbelow(high - low + 1)
    chosen_slots = list(available_slots)
    # secrets has no shuffle; sorting by random keys gives an unbiased enough
    # order for this small, non-cryptographic selection.
    chosen_slots.sort(key=lambda _: secrets.randbits(64))
    for slot in chosen_slots[:module_count]:
        module = _pick(_module_candidates(catalog, slot, safety_code))
        if not module:
            continue
        module_tokens = [
            token
            for token in (_clean_token(value, safety_code) for value in _tokens(module["text"]))
            if token
        ]
        if not module_tokens:
            continue
        tokens.extend(module_tokens[:3])
        components.append(
            {
                "slot": slot,
                "module_id": str(module.get("id", "")),
                "text": ", ".join(module_tokens[:3]),
            }
        )

    # Retain a little unclassified anchor detail so the selected scene remains
    # a coherent story rather than only a location name.
    tokens.extend(anchor_slots.get("detail", [])[:4])
    cleaned = _deduplicate(
        [value for value in (_clean_token(token, safety_code) for token in tokens) if value]
        + prefix,
        max(12, int(max_tags)),
    )
    # Prefix must stay first after final filtering.
    cleaned = _deduplicate([*prefix, *cleaned], max(12, int(max_tags)))
    prompt = ", ".join(cleaned)
    digest = hashlib.sha256(prompt.casefold().encode("utf-8")).hexdigest()[:12]
    prompt_id = f"kp-dyn-{safety_code.casefold()}-{digest}"
    level = {"N": "normal", "H": "nsfw", "S": "sexual"}[safety_code]
    anchor_category = next(
        (
            str(value)
            for value in anchor.get("categories", [])
            if str(value) not in {"kprompt", "dynamic"}
        ),
        "mixed",
    )
    return {
        "enabled": True,
        "weight": 1,
        "prompt_position": "suffix",
        "categories": ["kprompt", "dynamic", anchor_category],
        "source_group": "kprompt",
        "source_code": "K",
        "pair_id": str(anchor.get("pair_id", "")),
        "id": prompt_id,
        "name": f"K 动态{level}｜{anchor.get('name', anchor_category)}",
        "prompt": prompt,
        "safety_level": level,
        "safety_code": safety_code,
        "safety_matches": [] if safety_code == "N" else ["adult_dynamic"],
        "prompt_groups": ["dynamic", *[item["slot"] for item in components]],
        "runtime_generated": True,
        "dynamic_components": components,
        "content_hash": digest,
        "source": {
            "source_collection": catalog.get("source", {}).get("collection", "KP 00-14"),
            "source_commit": catalog.get("source", {}).get("commit", ""),
            "transformation": "runtime modular composition",
        },
    }


def assemble_dynamic_k_prompts(
    pool: dict[str, Any],
    catalog: dict[str, Any],
    count: int,
    *,
    safety_codes: list[str] | tuple[str, ...],
    preserve_character: bool = False,
    min_optional_modules: int = 4,
    max_optional_modules: int = 7,
    max_tags: int = 72,
    excluded_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    requested = max(1, int(count))
    excluded = set(excluded_ids or ())
    excluded.update(str(item.get("id", "")) for item in pool.get("trash", []) if isinstance(item, dict))
    excluded.update(str(item.get("id", "")) for item in pool.get("prompts", []) if isinstance(item, dict) and item.get("trashed"))
    result: list[dict[str, Any]] = []
    for _ in range(requested):
        for _attempt in range(40):
            item = assemble_dynamic_k_prompt(
                pool,
                catalog,
                safety_codes=safety_codes,
                preserve_character=preserve_character,
                min_optional_modules=min_optional_modules,
                max_optional_modules=max_optional_modules,
                max_tags=max_tags,
            )
            if item["id"] not in excluded:
                result.append(item)
                excluded.add(str(item["id"]))
                break
        else:
            raise WorkflowError("KP 动态拼装无法在限定次数内生成不重复结果。")
    return result


def persist_dynamic_k_entries(
    path: Path, entries: list[dict[str, Any]], *, history_limit: int = 2000
) -> int:
    if not entries:
        return 0
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            raise ValueError("prompts is not a list")
        by_id = {
            str(item.get("id", "")): item
            for item in prompts
            if isinstance(item, dict) and str(item.get("id", ""))
        }
        for item in entries:
            by_id[str(item["id"])] = dict(item)
        static = [item for item in by_id.values() if not bool(item.get("runtime_generated"))]
        dynamic = [item for item in by_id.values() if bool(item.get("runtime_generated"))]
        limit = max(50, int(history_limit))
        data["prompts"] = [*static, *dynamic[-limit:]]
        data.setdefault("dynamic_runtime", {})["history_count"] = len(dynamic[-limit:])
        temporary = path.with_name(f".{path.name}.dynamic.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return len(dynamic[-limit:])
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法保存 KP 动态结果：{exc}") from exc


def dynamic_k_history_count(pool: dict[str, Any]) -> int:
    return sum(
        1
        for item in pool.get("prompts", [])
        if isinstance(item, dict)
        and bool(item.get("runtime_generated"))
        and _DYNAMIC_K_ID.fullmatch(str(item.get("id", "")))
    )
