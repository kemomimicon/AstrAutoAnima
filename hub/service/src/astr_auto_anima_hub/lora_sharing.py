"""Public attribution links only. Never share model bytes or download credentials."""
import re
from urllib.parse import urlsplit, parse_qsl


def validate_public_source_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > 8192:
        raise ValueError("来源链接最多 8192 个字符")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("来源链接不能包含空白或控制字符")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请填写不含账号密码的公开 HTTP(S) 来源链接")
    if parsed.fragment or any(re.search(r"token|key|auth|signature|credential|secret", key, re.I)
                              for key, _ in parse_qsl(parsed.query)):
        raise ValueError("不能分享包含令牌、签名或凭据的下载链接，请填写公开作品页")
    if parsed.hostname.lower() in {"civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"}:
        if not re.fullmatch(r"/models/[1-9][0-9]*(?:/[^/]*)?/?", parsed.path):
            raise ValueError("Civitai 请填写公开模型页，不要填写 API 下载地址")
        for key, value_part in parse_qsl(parsed.query):
            if key != "modelVersionId" or not re.fullmatch(r"[1-9][0-9]*", value_part):
                raise ValueError("Civitai 来源仅保留 modelVersionId 版本参数")
    return value


def civitai_source_url(data: dict, version_id: int) -> str:
    model_id = data.get("modelId") or data.get("model", {}).get("id")
    if isinstance(model_id, int) and not isinstance(model_id, bool) and model_id > 0:
        return f"https://civitai.com/models/{model_id}?modelVersionId={version_id}"
    return ""
