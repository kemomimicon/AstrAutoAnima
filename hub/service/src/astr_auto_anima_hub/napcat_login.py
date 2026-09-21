"""Narrow local NapCat WebUI adapter; no account passwords or login bypass."""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field


class NapcatLoginRequest(BaseModel):
    uin: str = Field(default="", max_length=20, pattern=r"^\d*$")
    totp_code: str = Field(default="", max_length=8, pattern=r"^\d*$")


def login_state(status):
    if status.get('isOffline') is True:
        return 'offline'
    if status.get('isLogin') is True:
        return 'online'
    if status.get('isLogin') is False:
        return 'not_logged_in'
    return 'unknown'


async def napcat_request(payload: NapcatLoginRequest, *, login: bool = False, refresh_qr: bool = False, status_only: bool = False):
    base = os.getenv("AAH_NAPCAT_URL", "http://127.0.0.1:6099").rstrip("/")
    parsed = urlparse(base)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme not in {"http", "https"} or parsed.username or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise ValueError("NapCat 自动登录仅连接本机回环地址")
    token = os.getenv("AAH_NAPCAT_TOKEN", "").strip()
    if not token:
        path = Path(os.getenv("AAH_NAPCAT_WEBUI_CONFIG", ""))
        if not path.is_file():
            raise ValueError("未找到 NapCat Token；请配置 AAH_NAPCAT_TOKEN 或 AAH_NAPCAT_WEBUI_CONFIG")
        token = str(json.loads(path.read_text(encoding="utf-8-sig")).get("token", "")).strip()
    if not token:
        raise ValueError("NapCat Token 为空")
    async with httpx.AsyncClient(base_url=base, timeout=15, follow_redirects=False, trust_env=False) as client:
        async def call(route, body=None, credential=""):
            headers = {"Authorization": f"Bearer {credential}"} if credential else {}
            response = await client.post("/api" + route, json=body or {}, headers=headers)
            if response.status_code != 200:
                raise ValueError(f"NapCat 接口不可用（HTTP {response.status_code}）")
            data = response.json()
            if data.get("code") != 0:
                reason = str(data.get('message', data.get('msg', ''))).lower()
                hint = '请检查 Token、动态码、账号状态或版本兼容性'
                if 'token' in reason: hint = 'WebUI Token 无效；不是 OneBot Token，请核对实际运行配置路径'
                elif 'rate' in reason: hint = '登录请求过于频繁，请稍后重试'
                elif 'code' in reason: hint = '动态码无效或已过期，请重新输入'
                raise ValueError(f"NapCat {route} 拒绝请求：{hint}")
            return data.get("data")
        auth = await call("/auth/login", {"hash": hashlib.sha256((token + ".napcat").encode()).hexdigest(), "totpCode": payload.totp_code})
        if not isinstance(auth, dict): raise ValueError('NapCat 认证响应格式不兼容')
        if auth.get("require2FA"):
            return {"require_2fa": True, "message": "请输入 NapCat 双重验证动态码；不会关闭或绕过验证"}
        credential = str(auth.get("Credential", ""))
        if not credential:
            raise ValueError("NapCat 未返回登录凭据")
        status = await call("/QQLogin/CheckLoginStatus", credential=credential)
        if not isinstance(status, dict): raise ValueError('NapCat 状态响应格式不兼容')
        if status_only:
            from datetime import datetime, timezone
            state = login_state(status)
            return {'state': state, 'is_login': state == 'online',
                    'is_offline': state == 'offline',
                    'checked_at': datetime.now(timezone.utc).isoformat(),
                    'message': {'online': 'QQ 在线', 'offline': 'QQ 已掉线，请重新登录',
                                'not_logged_in': 'QQ 未登录', 'unknown': 'NapCat 未返回可识别的登录状态'}[state]}
        if refresh_qr and not status.get('isLogin'):
            await call('/QQLogin/RefreshQRcode', credential=credential)
            status = await call('/QQLogin/CheckLoginStatus', credential=credential)
        accounts = await call("/QQLogin/GetQuickLoginList", credential=credential)
        accounts = [str(value) for value in accounts if re.fullmatch(r"\d{5,20}", str(value))] if isinstance(accounts, list) else []
        if login:
            if status.get("isLogin"):
                raise ValueError("QQ 已经登录，不自动切换账号；如需切换请在 NapCat WebUI 操作")
            if payload.uin not in accounts:
                raise ValueError("该QQ不在已有快捷登录列表中，请先到NapCat扫码登录")
            await call("/QQLogin/SetQuickLogin", {"uin": payload.uin}, credential)
            return {"submitted": True, "message": "快捷登录已提交，请刷新状态；若要求扫码或设备验证，请到NapCat完成"}
        qr = str(status.get('qrcodeurl', '')) if not status.get('isLogin') else ''
        if len(qr) > 4096: qr = ''
        return {"is_login": bool(status.get("isLogin")), "is_offline": bool(status.get("isOffline")), "accounts": accounts, 'qr_code': qr,
                'message': 'QQ 已登录' if status.get('isLogin') else ('QQ 已掉线，请在 NapCat 完成重新登录' if status.get('isOffline') else '选择快捷账号或使用手机 QQ 扫码，确认后刷新状态')}
