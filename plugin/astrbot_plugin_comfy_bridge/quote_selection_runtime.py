import re
from .workflow_runtime import WorkflowError


def parse_selection(body):
    """Optional 1-based image list followed by an optional report reason."""
    text = str(body or '').strip().replace('，', ',')
    if not text or not text[0].isdigit():
        return None, text
    match = re.fullmatch(r'([0-9]+(?:\s*,\s*[0-9]+)*)(?:\s+(.*))?', text, re.S)
    if not match:
        raise WorkflowError('序号格式：1,3,5；只能选择 1–5，举报原因放在序号后用空格分隔')
    positions = list(dict.fromkeys(int(x.strip()) for x in match[1].split(',')))
    if any(x < 1 or x > 5 for x in positions):
        raise WorkflowError('五连抽序号只能为 1–5')
    return positions, (match[2] or '').strip()
