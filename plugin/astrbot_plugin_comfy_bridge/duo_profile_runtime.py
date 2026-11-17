"""Standalone two-character feature records and deterministic prompt preview.

Only the explicitly selected preset file is read. No plugin imports, servers,
models, LLMs or image-generation calls are involved.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

VERSION = "0.1.0-lab.1"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TEXT = 20000
FIELDS = {
    "hair": "头发短句（如 long copper-red hair）",
    "eyes": "眼睛短句（如 amber eyes）",
    "face": "面部／其他身份特征",
    "ear_species": "耳种类（如 fox；不确定留空）",
    "ear_shape": "耳形（如 triangular）",
    "ear_pose": "耳朝向（如 upright）",
    "ear_size": "耳大小（如 medium-sized）",
    "ear_outer": "耳外侧毛色（如 russet）",
    "ear_inner": "耳内侧毛色（如 cream）",
    "ear_markings": "耳部斑纹（如 black tips）",
    "human_ears": "人类耳可见情况（完整短句）",
    "tail": "尾巴（数量、形状、颜色完整短句）",
    "outfit": "服装／配饰完整短句",
    "other": "其他已确认外貌短句",
}
EAR_REQUIRED = ("ear_species", "ear_shape", "ear_pose", "ear_outer", "ear_inner")


class LabError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(data) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LabError(f"JSON 存在重复字段：{key}")
        result[key] = value
    return result


def _bad_constant(value):
    raise LabError(f"JSON 不接受非有限数字：{value}")


def read_json(path: Path):
    path = Path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise LabError("JSON 超过 16 MiB，请选择角色预设文件。")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_bad_constant)
        return data, raw
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LabError(f"读取 JSON 失败（{path.name}）：{exc}") from exc


def text(value, label: str, *, limit=MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise LabError(f"{label}必须是文本，且不能超过 {limit} 字符。")
    if any(ord(ch) < 32 and ch not in "\r\n\t" for ch in value):
        raise LabError(f"{label}含不可见控制字符。")
    return value


def _lora(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or not text(raw.get("name"), "LoRA 文件名", limit=1024).strip():
        raise LabError("LoRA 必须包含 name 文件名。")
    result = {"name": raw["name"]}  # Keep the server's exact path and case.
    for key, fallback in (("strength_model", 1.0), ("strength_clip", raw.get("strength_model", 1.0))):
        value = raw.get(key, fallback)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -5 <= value <= 5:
            raise LabError(f"LoRA {key} 必须是 -5 到 5 的有限数字。")
        result[key] = value
    return result


def normalize_character(name, raw):
    name = text(name, "角色名", limit=200)
    if not name.strip() or not isinstance(raw, dict):
        raise LabError("角色名不能为空，角色预设必须是对象。")
    prompt = text(raw.get("prompt", ""), "角色固定提示词")
    if "lora" in raw:
        lora = _lora(raw["lora"])
        if "loras" in raw and raw["loras"] not in ([], [lora]):
            raise LabError("同时包含不同的 lora 与 loras，请选择原始 presets.json。")
    else:
        loras = raw.get("loras", [])
        if not isinstance(loras, list) or len(loras) > 1:
            raise LabError("每个角色目前只接受一个角色 LoRA。")
        lora = _lora(loras[0]) if loras else None
    variants = raw.get("variants", [])
    if not isinstance(variants, list) or len(variants) > 64:
        raise LabError("variants 必须是最多 64 项的列表。")
    found, seen = [], {"default", "默认"}
    for row in variants:
        if not isinstance(row, dict):
            raise LabError("造型必须是对象。")
        ident = text(row.get("id"), "造型 ID", limit=100)
        if not ident.strip() or ident in seen:
            raise LabError("造型 ID 为空、重复或占用 default／默认。")
        seen.add(ident)
        value = text(row.get("prompt", ""), "造型提示词")
        if not value.strip(" ,\n\t"):
            raise LabError(f"造型 {ident} 的提示词为空。")
        found.append({"id": ident, "name": text(row.get("name", ident), "造型名称", limit=200), "prompt": value})
    return {"name": name, "prompt": prompt, "lora": lora, "variants": found}


@dataclass
class Catalog:
    path: Path
    file_sha256: str
    characters: dict
    errors: list[str]


def load_catalog(path: Path) -> Catalog:
    path = Path(path).expanduser().resolve(strict=True)
    payload, raw = read_json(path)
    if not isinstance(payload, dict) or "characters" not in payload:
        raise LabError("请选择含 characters 的 presets.json，或含 characters 列表的 Hub 导出。")
    rows = payload["characters"]
    if isinstance(rows, dict):
        pairs = list(rows.items())
    elif isinstance(rows, list):
        if any(not isinstance(row, dict) for row in rows):
            raise LabError("characters 列表含非对象。")
        pairs = [(row.get("name"), row) for row in rows]
    else:
        raise LabError("characters 必须是对象或列表。")
    if len(pairs) > 10000:
        raise LabError("角色超过 10000 项，请分批导出。")
    found, errors, seen = {}, [], set()
    for name, value in pairs:
        if isinstance(name, str) and name in seen:
            raise LabError(f"角色名称重复：{name}")
        if isinstance(name, str):
            seen.add(name)
        try:
            if isinstance(value, dict) and value.get("kind", "character") != "character":
                raise LabError("条目 kind 不是 character")
            found[name] = normalize_character(name, value)
        except LabError as exc:
            errors.append(f"{str(name)[:80]}：{exc}")
    if not found:
        raise LabError("没有可读取的角色。" + "；".join(errors[:3]))
    return Catalog(path, digest(raw), found, errors)


def new_profile(catalog: Catalog, name: str, variant_id="default") -> dict:
    if name not in catalog.characters:
        raise LabError("角色不存在，请重新选择。")
    char = copy.deepcopy(catalog.characters[name])
    if variant_id == "default":
        prompt, variant_name = char["prompt"], "默认"
    else:
        matches = [v for v in char["variants"] if v["id"] == variant_id]
        if len(matches) != 1:
            raise LabError("造型不存在。")
        prompt, variant_name = matches[0]["prompt"], matches[0]["name"]
    return {
        "schema_version": 1, "profile_id": uuid.uuid4().hex, "revision": 0,
        "label": name if variant_id == "default" else f"{name} · {variant_name}",
        "source": {"path": str(catalog.path), "file_sha256": catalog.file_sha256,
                   "character_sha256": digest(json_bytes(char)), "name": name,
                   "variant_id": variant_id, "variant_name": variant_name,
                   "selected_prompt": prompt, "lora": char["lora"]},
        "composition_mode": "original", "identity_text": "",
        "features": {}, "notes": "", "_etag": None,
    }


def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        raise LabError("不支持的特征档案格式。")
    if not re.fullmatch(r"[a-f0-9]{32}", str(profile.get("profile_id", ""))):
        raise LabError("特征档案 ID 无效。")
    if type(profile.get("revision")) is not int or profile["revision"] < 0:
        raise LabError("档案 revision 无效。")
    if not text(profile.get("label"), "档案名称", limit=300).strip():
        raise LabError("请填写档案名称。")
    source = profile.get("source")
    if not isinstance(source, dict):
        raise LabError("档案缺少来源快照。")
    for key in ("path", "name", "variant_id", "variant_name", "selected_prompt"):
        text(source.get(key), f"来源 {key}")
    for key in ("file_sha256", "character_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(source.get(key, ""))):
            raise LabError("来源哈希无效。")
    _lora(source.get("lora"))
    if profile.get("composition_mode") not in {"original", "curated"}:
        raise LabError("请选择原预设或已整理触发词模式。")
    text(profile.get("identity_text", ""), "身份／触发词")
    text(profile.get("notes", ""), "备注")
    features = profile.get("features")
    if not isinstance(features, dict) or set(features) - set(FIELDS):
        raise LabError("特征字段格式或名称无效。")
    for key, field in features.items():
        if not isinstance(field, dict) or type(field.get("confirmed")) is not bool:
            raise LabError(f"特征 {key} 缺少确认状态。")
        text(field.get("text"), FIELDS[key], limit=2000)
        text(field.get("source"), f"{key} 来源", limit=300)
    if type(profile.get("identity_confirmed", False)) is not bool:
        raise LabError("触发词确认状态无效。")
    return profile


def source_status(profile: dict) -> str:
    """Explicitly called by the GUI, not by preview: snapshots work offline."""
    validate_profile(profile)
    try:
        catalog = load_catalog(Path(profile["source"]["path"]))
    except (LabError, OSError):
        return "来源文件不可读；当前仍使用已保存快照。"
    char = catalog.characters.get(profile["source"]["name"])
    if char is None:
        return "来源角色已改名或移除；当前快照保留，请手动选择重建。"
    if digest(json_bytes(char)) != profile["source"]["character_sha256"]:
        return "来源角色已变化；当前快照保留，可新建档案作对照。"
    if catalog.file_sha256 != profile["source"]["file_sha256"]:
        return "来源文件其他内容有变化；本角色内容一致。"
    return "来源角色与快照一致。"


def _sentence(parts):
    # Preserve punctuation, casing, escaped parentheses and weighting inside each
    # fragment. In particular do not split raw preset text on comma or period.
    clean, seen = [], set()
    for part in parts:
        value = part.strip(" ,，\r\n\t")
        if value and value not in seen:
            seen.add(value)
            clean.append(value)
    result = ""
    for value in clean:
        if result:
            result += " " if result.endswith((".", "。", "!", "?", "！", "？")) else ", "
        result += value
    if result and not result.endswith((".", "。", "!", "?", "！", "？")):
        result += "."
    return result


def _feature_fragments(values):
    result = [values.get(k, "") for k in ("hair", "eyes", "face")]
    ear = [values.get(k, "") for k in ("ear_size", "ear_pose", "ear_shape", "ear_species")]
    if any(ear) or any(values.get(k) for k in ("ear_outer", "ear_inner", "ear_markings")):
        head = " ".join(x for x in ear if x)
        if not head.endswith("ears"):
            head = (head + " ears").strip()
        details = [values["ear_outer"] + " outer fur"] if values.get("ear_outer") else []
        if values.get("ear_inner"):
            details.append(values["ear_inner"] + " inner fur")
        if values.get("ear_markings"):
            details.append(values["ear_markings"])
        result.append(head + (" with " + " and ".join(details) if details else ""))
    result.extend(values.get(k, "") for k in ("human_ears", "tail", "outfit", "other"))
    return result


def compile_preview(actors: list[dict], shared: dict) -> dict:
    if not isinstance(actors, list) or len(actors) != 2:
        raise LabError("本实验版只编排两个人物。")
    if not isinstance(shared, dict):
        raise LabError("场景必须是对象。")
    issues, paragraphs, snapshots, loras = [], [], [], []
    for index, actor in enumerate(actors):
        if not isinstance(actor, dict):
            raise LabError("人物数据必须是对象。")
        slot = "AB"[index]
        profile = validate_profile(copy.deepcopy(actor.get("profile")))
        profile.pop("_etag", None)
        values = {}
        for key, field in profile["features"].items():
            if field["text"].strip() and not field["confirmed"]:
                raise LabError(f"人物 {slot} 的“{FIELDS[key]}”尚未确认。请确认或清空该字段。")
            values[key] = field["text"].strip()
        if profile["composition_mode"] == "curated":
            if not profile.get("identity_confirmed") or not profile["identity_text"].strip():
                raise LabError(f"人物 {slot} 请填写并确认整理后的身份／触发词。")
            prefix = profile["identity_text"]
        else:
            prefix = profile["source"]["selected_prompt"]
        if not prefix.strip():
            raise LabError(f"人物 {slot} 的预设提示词为空；请整理并确认身份／触发词。")
        position = text(actor.get("position", ""), "人物位置", limit=2000)
        action = text(actor.get("action", ""), "人物动作", limit=2000)
        prompt = _sentence([prefix, *_feature_fragments(values), position, action])
        paragraphs.append(prompt)
        snapshots.append({"slot": slot, "profile": profile, "position": position, "action": action})
        if re.search(r"(?<![\w])solo(?![\w])", prompt, re.I):
            issues.append(f"人物 {slot} 含 solo，请检查是否与双人画面冲突；原文已保留。")
        if re.search(r"\b[2-9]\s*(girls?|boys?|people|persons?)\b", prompt, re.I):
            issues.append(f"人物 {slot} 段内含多个人数词，请检查归属。")
        if any(values.get(k) for k in values if k.startswith("ear_")):
            missing = [FIELDS[k] for k in EAR_REQUIRED if not values.get(k)]
            if missing:
                issues.append(f"人物 {slot} 耳部待补充：{'、'.join(missing)}；没有补写未知特征。")
        if not any(values.values()):
            issues.append(f"人物 {slot} 尚无独立特征，预览沿用当前选择的提示词。")
        if re.search(r"\banimal ears?\b", prompt, re.I) and not values.get("ear_species"):
            issues.append(f"人物 {slot} 耳种类仍是宽泛描述，可补充具体种类、形状和颜色。")
        if profile["composition_mode"] == "original" and any(values.values()):
            issues.append(f"人物 {slot} 保留原提示词并追加特征，请检查原文与新增属性有无冲突。")
        lora = profile["source"].get("lora")
        if lora:
            loras.append({"slot": slot, **copy.deepcopy(lora)})
    shared_values = {k: text(shared.get(k, ""), k, limit=4000) for k in ("interaction", "scene", "composition", "style_lighting")}
    paragraphs.append(_sentence(["Exactly two people", *shared_values.values()]))
    prompt = "\n\n".join(paragraphs)
    if len(prompt) > 60000:
        raise LabError("最终文本过长，请缩短人物和场景描述。")
    if re.search(r"[\u3400-\u9fff]", prompt):
        issues.append("最终文本含中文；工具不会自动翻译或改写，请核对当前模型的输入要求。")
    if re.search(r"\b(?:[013-9]|[1-9][0-9]+)\s*(?:girls?|boys?|people|persons?)\b|\bsolo\b", " ".join(shared_values.values()), re.I):
        issues.append("共享场景含可能与两个人物冲突的人数／solo 词。")
    if snapshots[0]["profile"]["profile_id"] == snapshots[1]["profile"]["profile_id"]:
        issues.append("两个人物使用同一档案，请确认这是你的意图。")
    names = [l["name"].replace("\\", "/").casefold() for l in loras]
    if len(names) != len(set(names)):
        issues.append("两个人物引用同名 LoRA，列表保留各自权重，未自动合并或加载。")
    if loras:
        issues.append("LoRA 列表仅供核对；复制提示词不会加载 LoRA，也不建立区域隔离。")
    return {"schema_version": 1, "compiler": VERSION, "mode": "preview_only",
            "prompt": prompt, "paragraphs": paragraphs, "actors": snapshots,
            "shared": shared_values, "lora_references": loras, "issues": issues,
            "negative_prompt": None, "negative_note": "未读取或修改工作流负向提示词。"}


def default_data_root() -> Path:
    # Always independent of AstrBot/Hub, including a portable frozen executable.
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local/share"
    return root / "AstrAutoAnima-DuoLab"


def _no_redirects(path: Path):
    path = Path(os.path.abspath(path))
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise LabError("实验数据路径不能经过符号链接或目录联接。")
    return path


class ProfileStore:
    MARKER = ".aaa-duo-lab-v1"

    def __init__(self, root: Path):
        self.root = _no_redirects(Path(root).expanduser())
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / self.MARKER
        _no_redirects(marker)
        if not marker.exists():
            if any(self.root.iterdir()):
                raise LabError("请选择空的独立实验数据目录，不能使用已有插件／配置目录。")
            with marker.open("x", encoding="utf-8") as stream:
                stream.write("AAA Duo Character Lab data v1\n")
        elif not marker.is_file() or marker.read_text(encoding="utf-8") != "AAA Duo Character Lab data v1\n":
            raise LabError("实验目录标记无效。")
        for name in ("profiles", "backups", "previews"):
            self._path(name).mkdir(exist_ok=True)

    def _path(self, relative):
        path = _no_redirects(self.root / relative)
        if not path.is_relative_to(self.root):
            raise LabError("实验数据路径越界。")
        return path

    @contextmanager
    def _lock(self):
        path = self._path(".write.lock")
        try:
            stream = path.open("x", encoding="ascii")
        except FileExistsError as exc:
            raise LabError("另一窗口正在保存，或上次保存被中断。请关闭其他窗口后检查 .write.lock。") from exc
        try:
            with stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            path.unlink(missing_ok=True)

    def _new_file(self, relative, raw):
        path = self._path(relative)
        created = False
        try:
            with path.open("xb") as stream:
                created = True
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            if created:
                path.unlink(missing_ok=True)
            raise
        return path

    def load(self, ident):
        if not re.fullmatch(r"[a-f0-9]{32}", str(ident)):
            raise LabError("档案 ID 无效。")
        value, raw = read_json(self._path(f"profiles/{ident}.json"))
        validate_profile(value)
        if value["profile_id"] != ident:
            raise LabError("档案 ID 与文件名不一致。")
        value["_etag"] = digest(raw)
        return value

    def list_profiles(self):
        values, errors = [], []
        for path in sorted(self._path("profiles").glob("*.json")):
            try:
                values.append(self.load(path.stem))
            except LabError as exc:
                errors.append(f"{path.name}：{exc}")
        return values, errors

    def save(self, profile):
        value = copy.deepcopy(validate_profile(profile))
        expected = value.pop("_etag", None)
        ident = value["profile_id"]
        with self._lock():
            target = self._path(f"profiles/{ident}.json")
            old = target.read_bytes() if target.exists() else None
            if old is None and (expected is not None or value["revision"] != 0):
                raise LabError("原档案已移除，未重新创建；请加载最新状态或新建档案。")
            if old is not None:
                current = self.load(ident)
                if not expected or digest(old) != expected or current["revision"] != value["revision"]:
                    raise LabError("档案已被另一窗口修改，未覆盖。请保留当前草稿并重新加载。")
                if current["source"] != value["source"]:
                    raise LabError("来源快照不可覆盖；请选择角色新建独立档案。")
                backup = f"backups/{ident}-r{value['revision']}-{uuid.uuid4().hex}.json"
                backup_path = self._new_file(backup, old)
                if digest(backup_path.read_bytes()) != digest(old):
                    raise LabError("备份校验失败，未保存。")
            value["revision"] += 1
            value["updated_at"] = datetime.now(timezone.utc).isoformat()
            raw = json_bytes(value)
            temp = self._new_file(f"profiles/.{ident}-{uuid.uuid4().hex}.tmp", raw)
            try:
                self._path(f"profiles/{ident}.json")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        value["_etag"] = digest(raw)
        return value

    def save_preview(self, result):
        # Recompile the exact snapshot instead of accepting an arbitrary prompt.
        compiled = compile_preview(result["actors"], result["shared"])
        if compiled["prompt"] != result["prompt"]:
            raise LabError("预览与人物快照不一致，请重新生成预览。")
        ident = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        with self._lock():
            json_path = self._new_file(f"previews/{ident}.json", json_bytes(compiled))
            try:
                txt_path = self._new_file(f"previews/{ident}.txt", compiled["prompt"].encode("utf-8"))
            except OSError:
                json_path.unlink(missing_ok=True)
                raise
        return json_path, txt_path
