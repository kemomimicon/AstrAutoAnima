from __future__ import annotations
import secrets
from .workflow_runtime import WorkflowError


def choose_chaos_style(catalog: dict) -> dict:
    entries = catalog.get("entries", {})
    candidates = [dict(value, path=path) for path, value in entries.items()
                  if isinstance(value, dict) and value.get("category") == "style"
                  and value.get("enabled", True) and value.get("present", False)]
    if len(candidates) < 3:
        raise WorkflowError("混沌时刻至少需要3个已扫描且有效的画风LoRA。请在管理端分类并重新扫描。")
    rng = secrets.SystemRandom()
    chosen = rng.sample(candidates, rng.randint(3, min(5, len(candidates))))
    # Budget in hundredths avoids float overflow beyond 1.5.
    remaining = 150
    loras, triggers, seen = [], [], set()
    for i, item in enumerate(chosen):
        if i == 0:
            strength = rng.randint(70, 90)
        else:
            reserved = 10 * (len(chosen) - i - 1)
            strength = rng.randint(10, min(60, remaining - reserved))
            remaining -= strength
        loras.append({"name": item["path"], "strength_model": strength / 100, "strength_clip": strength / 100})
        for trigger in str(item.get("recommended_prompt", "")).split(","):
            trigger = trigger.strip()
            normalized = " ".join(trigger.lower().replace("_", " ").split())
            if normalized and normalized not in seen:
                seen.add(normalized)
                triggers.append(trigger)
    return {"loras": loras, "prompt": ", ".join(triggers), "match": []}
