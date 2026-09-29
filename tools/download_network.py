"""Opt-in network settings for public artifact downloads only (not service APIs)."""
from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DownloadNetwork:
    mode: str = 'official'
    hf_mirror: str = ''
    github_mirror: str = ''
    proxy: str = ''
    revoke_best_effort: bool = False

    @classmethod
    def from_plan(cls, plan):
        return cls(*(getattr(plan, key, default) for key, default in (
            ('download_mode', 'official'), ('hf_mirror', ''), ('github_mirror', ''),
            ('download_proxy', ''), ('revoke_best_effort', False))))

    def validate(self):
        if self.mode not in {'official', 'mirror', 'proxy', 'local'}:
            raise ValueError('下载模式必须为 official / mirror / proxy / local')
        for value in (self.hf_mirror, self.github_mirror):
            if value:
                self._url(value, {'https'})
        if self.proxy:
            self._url(self.proxy, {'http', 'https', 'socks5', 'socks5h'}, proxy=True)
        if self.mode == 'proxy' and not self.proxy:
            raise ValueError('代理模式需要填写本机可访问的代理地址')
        if self.mode == 'mirror' and not (self.hf_mirror or self.github_mirror):
            raise ValueError('镜像模式至少填写一项 HTTPS 镜像；未填写的来源仍走官方')
        if self.revoke_best_effort and os.name != 'nt':
            raise ValueError('证书吊销离线兼容仅用于 Windows Schannel curl')

    @staticmethod
    def _url(value, schemes, proxy=False):
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme in schemes and parsed.hostname and
                     parsed.username is None and parsed.password is None and
                     not parsed.query and not parsed.fragment and
                     not any(c.isspace() or c in '\\"\'' for c in value))
            parsed.port  # Reject malformed ports before invoking curl.
            if proxy and parsed.path not in ('', '/'):
                valid = False
            if not valid:
                raise ValueError()
        except ValueError:
            raise ValueError('下载地址格式无效：须为完整 URL，不允许账号、密码、查询令牌或空白') from None

    def source(self, url, expected_sha256):
        self.validate()
        if self.mode == 'local':
            raise ValueError('本地文件模式禁止自动下载：请选择本地模型 / AM ZIP，或提供已校验的缓存文件')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('公开下载仅允许无凭据的 HTTPS 来源')
        selected = url
        if self.mode == 'mirror':
            if parsed.netloc == 'huggingface.co' and self.hf_mirror:
                selected = self.hf_mirror.rstrip('/') + parsed.path
                if parsed.query:
                    selected += '?' + parsed.query
            elif parsed.netloc in {'github.com', 'codeload.github.com', 'raw.githubusercontent.com'} and self.github_mirror:
                selected = self.github_mirror.rstrip('/') + '/' + url
        if selected != url and (len(expected_sha256) != 64 or
                                any(c not in '0123456789abcdefABCDEF' for c in expected_sha256)):
            raise ValueError('镜像下载必须有发布清单中的 SHA256；该项目未提供哈希，请改用官方源或代理')
        return selected


def failure_message(code, detail):
    if 'CRYPT_E_REVOCATION_OFFLINE' in detail or '0x80092013' in detail.lower():
        return ('Windows 无法访问证书吊销检查服务器；这不等于 GitHub 文件不存在。'
                '检查系统时间及网络/代理；仅对此错误，可自行勾选「证书吊销离线兼容」后重试。')
    if code in (5, 6, 7, 28):
        return ('DNS、连接或传输超时：可选择模型镜像、文件下载代理，或手动下载后选择本地文件。'
                '浏览器能下载不代表系统 curl 使用了浏览器的代理。')
    if code == 60:
        return '服务器证书验证失败：检查系统时间、系统证书或代理证书；不会关闭证书验证。'
    if code in (33, 36) or (code == 22 and '416' in detail):
        return '服务器不支持当前断点续传；请保留 .part 文件并换源，或手动下载完整文件后导入。'
    if code == 22:
        return '下载地址返回 HTTP 错误；检查镜像是否支持该完整路径，或使用官方源/本地导入。'
    return '下载失败；请保留错误码和日志，或使用本地文件导入。'


def fetch_public_file(curl, url, partial, log, network):
    """Bounded stalls/retries; no shell, curlrc, cookies, API keys or TLS bypass."""
    args = [curl, '--disable', '--location', '--fail', '--show-error', '--silent',
            '--proto', '=https', '--proto-redir', '=https', '--retry', '2',
            '--retry-delay', '3', '--retry-max-time', '150', '--connect-timeout', '20',
            '--speed-limit', '1024', '--speed-time', '45', '--max-time', '14400',
            '--continue-at', '-', '--output', str(partial)]
    # Do not inherit an unrelated proxy from the parent environment/curl config.
    args += ['--proxy', network.proxy if network.mode == 'proxy' else '']
    if network.mode == 'proxy':
        args += ['--noproxy', '']
    if network.revoke_best_effort:
        check = subprocess.run([curl, '--disable', '--version'], capture_output=True,
                               text=True, errors='replace', timeout=10,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if check.returncode or 'Schannel' not in check.stdout:
            raise ValueError('此 curl 不是 Schannel 构建，请取消证书吊销离线兼容选项')
        args += ['--ssl-revoke-best-effort']
        log('已明确启用吊销离线兼容：仍验证证书链/主机名，不忽略已知吊销证书；降低离线吊销检查保障。')
    log(f'开始公开文件下载（{network.mode}）；失败最多重试 2 次，断点保存在 .part。')
    log('大文件可需较长时间；下方每 15 秒显示已下载大小。')
    # Capture only curl errors, not progress bars or potentially signed redirects.
    with subprocess.Popen(args + [url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
        while True:
            try:
                output, _ = process.communicate(timeout=15)
                break
            except subprocess.TimeoutExpired:
                size = partial.stat().st_size if partial.is_file() else 0
                log(f'已下载 {size / 1024**2:.1f} MiB（等待响应时可能暂不增长）')
        if process.returncode:
            detail = output.decode('utf-8', errors='replace')
            raise ValueError(f'curl 退出码 {process.returncode}：{failure_message(process.returncode, detail)}\n'
                             f'{detail[-2000:]}\n未删除已有文件；可在同一安装目录重试。')
