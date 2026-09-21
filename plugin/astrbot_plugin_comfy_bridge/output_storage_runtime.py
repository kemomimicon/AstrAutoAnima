"""Apply persisted storage preferences without touching model or workflow files."""
from __future__ import annotations
import json
import os
import re
import struct
import uuid
from pathlib import Path


def safe_path(path):
    path = Path(os.path.abspath(path))
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("图片路径包含链接，拒绝操作")
    return path


def preferences(data_root):
    path = safe_path(Path(data_root) / "image_storage.json")
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def component(value):
    return re.sub(r'[^\w\u4e00-\u9fff.-]+', '_', str(value)).strip('._')[:80] or "未指定"


def configure_output(workflow, settings, *, style="", character="", user="", palette=False):
    group = settings.get("grouping", "original")
    if palette:
        prefix = "AAA-RandomStyle/" + uuid.uuid4().hex
    elif group in {"style", "character", "user"}:
        value = {"style": style, "character": character, "user": user}[group]
        prefix = "AAA-" + group + "/" + component(value) + "/AAA"
    else:
        return
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            node.setdefault("inputs", {})["filename_prefix"] = prefix


def strip_png_metadata(content):
    """Remove embedded text/EXIF only, leave IDAT and color chunks byte-identical."""
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("当前无损去元数据仅支持 PNG，未修改原文件")
    output = bytearray(content[:8])
    offset = 8
    while offset < len(content):
        if offset + 12 > len(content):
            raise ValueError("PNG 数据不完整")
        size = struct.unpack(">I", content[offset:offset + 4])[0]
        end = offset + 12 + size
        if end > len(content):
            raise ValueError("PNG 数据不完整")
        kind = content[offset + 4:offset + 8]
        if kind not in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
            output.extend(content[offset:end])
        offset = end
        if kind == b"IEND":
            return bytes(output)
    raise ValueError("PNG 缺少结束标记")


def atomic_bytes(path, content):
    path = safe_path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("xb") as stream:
        stream.write(content)
    os.replace(temp, path)


def strip_outputs(paths, refs, output_root):
    root = safe_path(output_root)
    for path in paths:
        atomic_bytes(path, strip_png_metadata(safe_path(path).read_bytes()))
    for ref in refs:
        if ref.get("type", "output") != "output":
            continue
        path = safe_path(root / ref.get("subfolder", "") / ref["filename"])
        if not path.is_relative_to(root):
            raise ValueError("ComfyUI 返回非法输出路径")
        if not path.is_file():
            raise ValueError("本机无法访问 ComfyUI 输出，未清除服务器元数据")
        atomic_bytes(path, strip_png_metadata(path.read_bytes()))


def watermark_image(source, data_root, output_root, settings):
    """Non-destructive PNG derivative; callers must audit before delivery."""
    from PIL import Image, ImageOps
    signature = safe_path(Path(data_root) / "signature.png")
    folder = str(settings.get("watermark_folder", "Author Pictures"))
    if folder.casefold() in {".", "..", "aaa-randomstyle", "aaa-style", "aaa-character", "aaa-user", "models", "workflows"} or not re.fullmatch(r"[\w -]{1,80}", folder):
        raise ValueError("签名文件夹必须是独立的单层目录名")
    target_dir = safe_path(Path(output_root) / folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(safe_path(source)) as opened, Image.open(signature) as mark:
        if opened.width * opened.height > 64_000_000 or mark.width * mark.height > 4_000_000:
            raise ValueError("图片尺寸超出水印处理限制")
        canvas = ImageOps.exif_transpose(opened).convert("RGBA")
        overlay = mark.convert("RGBA")
        overlay.thumbnail((max(1, canvas.width // 5), max(1, canvas.height // 5)))
        margin = max(8, min(canvas.size) // 50)
        corner = settings.get("watermark_corner", "bottom-right")
        x = margin if corner.endswith("left") else canvas.width - overlay.width - margin
        y = margin if corner.startswith("top") else canvas.height - overlay.height - margin
        canvas.alpha_composite(overlay, (max(0, x), max(0, y)))
        target = safe_path(target_dir / (uuid.uuid4().hex + ".png"))
        with target.open("xb") as stream:
            canvas.save(stream, format="PNG")
    return target
