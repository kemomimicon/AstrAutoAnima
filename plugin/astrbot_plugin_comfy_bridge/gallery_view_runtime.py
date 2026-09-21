"""Read published gallery previews without generating or changing anything."""
import json
import re
from pathlib import Path
from .workflow_runtime import WorkflowError

SCENES = ('水上秋千', '温馨室内', '夜晚野外', '海底漫步')


def gallery_view(plugin_data, query=''):
    base = Path(plugin_data).resolve()
    root = base / 'style_gallery'
    def checked(name):
        path = root / name
        if (root.is_symlink() or getattr(root, 'is_junction', lambda: False)()
            or path.is_symlink() or not path.resolve().is_relative_to(root)):
            raise WorkflowError('画廊路径异常，停止读取')
        return path
    manifest = checked('gallery.json')
    if not manifest.is_file():
        return '画廊尚未建立，请管理员先在管理端生成画风预览。此指令不会自动跑图。', []
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    items = sorted(data.get('items', []), key=lambda item: str(item.get('style', '')).casefold())
    if not items:
        return '画廊暂无画风预览，请管理员先更新画廊。', []
    query = str(query).strip()
    if query.startswith('画风='):
        query = query[3:].strip()
    if len(query) >= 2 and query[0] == query[-1] and query[0] in {'"', "'"}:
        query = query[1:-1]
    page_match = re.fullmatch(r'页\s*=\s*([1-9][0-9]*)', query)
    if not query or page_match:
        page = int(page_match[1]) if page_match else 1
        pages = max(1, (len(items) + 9) // 10)
        if page > pages:
            raise WorkflowError(f'画廊共 {pages} 页，请发送 查看画廊 页=1')
        lines = [f'画风画廊｜第 {page}/{pages} 页｜共 {len(items)} 个画风']
        for item in items[(page-1)*10:page*10]:
            ready = sum(slot.get('status') == 'succeeded' and bool(slot.get('file')) for slot in item.get('slots', []))
            lines.append(f"{item['style']}｜已生成 {ready}/4")
        lines.append('查看画廊 画风名称：查看四张预览；查看画廊 页=2：翻页。只读取已有图片，不新建任务。')
        return '\n'.join(lines), []
    selected = [item for item in items if item.get('style') == query]
    if not selected:
        selected = [item for item in items if query.casefold() in str(item.get('style', '')).casefold()]
    if not selected:
        raise WorkflowError('画廊中没有这个画风。发送“查看画廊”查看已有名称；未生成的预设不会自动生成。')
    if len(selected) != 1:
        return '匹配多个画风，请填写完整名称：\n' + '\n'.join(str(item['style']) for item in selected[:20]), []
    item = selected[0]
    images, missing = [], []
    seen = set()
    for slot in sorted(item.get('slots', []), key=lambda slot: slot.get('index', -1)):
        index = slot.get('index')
        if not isinstance(index, int) or index not in range(4) or index in seen:
            raise WorkflowError('画廊预览序号异常，请管理员更新画廊')
        seen.add(index)
        name = str(slot.get('file', ''))
        if slot.get('status') != 'succeeded' or not name:
            missing.append(str(index + 1))
            continue
        if not re.fullmatch(r'[a-f0-9]{32}\.image', name):
            raise WorkflowError('画廊图片文件名异常')
        path = checked(name)
        if not path.is_file():
            missing.append(str(index + 1))
            continue
        images.append((f"画廊｜{item['style']}｜{index+1}/4 · {SCENES[index]}", path))
    missing.extend(str(index + 1) for index in range(4) if index not in seen)
    text = f"画风：{item['style']}｜现有预览 {len(images)}/4（非本次生图）"
    if missing:
        text += '\n未就绪或已清理：' + ','.join(missing) + '；请管理员更新画廊。'
    return text, images
