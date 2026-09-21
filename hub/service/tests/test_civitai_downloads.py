import unittest
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from astr_auto_anima_hub.civitai_downloads import CivitaiDownloads
from astr_auto_anima_hub.civitai_downloads import DownloadRequest, safe_download_url, select_file


class CivitaiTests(unittest.TestCase):
    def test_directory_limits_before_filesystem_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = CivitaiDownloads(SimpleNamespace(lora_root=root / 'loras', hub_state_dir=root / 'state'))
            for value in ['a' * 81, '\U00020000' * 80, '../escape', '/absolute', 'a/' * 101]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    manager.destination(value, create=True)
            self.assertFalse((root / 'loras').exists())
            self.assertEqual(DownloadRequest(version_id=1, file_id=1, expected_sha256='a'*64).subdirectory, 'anima_lora')

    def data(self):
        return {"model": {"type": "LORA"}, "baseModel": "Anima", "trainedWords": ["example"],
                "files": [{"id": 9, "name": "test.safetensors", "type": "Model", "sizeKB": 100,
                           "hashes": {"SHA256": "a" * 64}, "virusScanResult": "Success", "pickleScanResult": "Success",
                           "downloadUrl": "https://civitai.com/api/download/models/1"}]}

    def test_selection(self):
        request = DownloadRequest(version_id=1, file_id=9, expected_sha256="a" * 64)
        self.assertEqual(select_file(self.data(), request, 1000000)["size_bytes"], 102400)

    def test_source_is_public_version_page(self):
        data = self.data()
        data["modelId"] = 42
        item = select_file(data, DownloadRequest(version_id=1, file_id=9, expected_sha256="a" * 64), 1000000)
        self.assertEqual(item["source_url"], "https://civitai.com/models/42?modelVersionId=1")

    def test_mismatch(self):
        request = DownloadRequest(version_id=1, file_id=9, expected_sha256="b" * 64)
        with self.assertRaises(ValueError):
            select_file(self.data(), request, 1000000)

    def test_incompatible(self):
        data = self.data()
        data["baseModel"] = "SDXL"
        with self.assertRaises(ValueError):
            select_file(data, DownloadRequest(version_id=1, file_id=9, expected_sha256="a" * 64), 1000000)


class DownloadStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_redirect_does_not_leak_token(self):
        content = b"test-model-content"
        sha = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = CivitaiDownloads(SimpleNamespace(lora_root=root / "loras", hub_state_dir=root / "state"))
            manager.token = "private-token"
            target = root / "loras" / "civitai"
            target.mkdir(parents=True)
            job = {"id": "a" * 32, "version_id": 1, "status": "queued", "downloaded": 0}
            (target / f".{job['id']}.part").write_bytes(content[:4])
            seen = []

            def handler(request):
                seen.append(request)
                if request.url.host == "civitai.com":
                    return httpx.Response(302, headers={"location": "https://models.civitai.com/file"})
                return httpx.Response(206, headers={"content-range": f"bytes 4-{len(content)-1}/{len(content)}"}, content=content[4:])

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch("astr_auto_anima_hub.civitai_downloads.httpx.AsyncClient", return_value=client), patch("astr_auto_anima_hub.civitai_downloads.scan_loras"):
                await manager.run(job, {"url": "https://civitai.com/api/download/models/1", "sha256": sha, "size_bytes": len(content)})
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(Path(job["path"]).read_bytes(), content)
            self.assertEqual(seen[0].headers["authorization"], "Bearer private-token")
            self.assertNotIn("authorization", seen[1].headers)
            self.assertEqual(seen[1].headers["range"], "bytes=4-")

    def test_reject_ssrf_and_http(self):
        for url in ["http://civitai.com/a", "https://127.0.0.1/a", "https://civitai.com.evil.test/a", "https://token@civitai.com/a", "https://civitai.com:8080/a"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                safe_download_url(url)

    def test_pending_scan(self):
        data = CivitaiTests().data()
        data["files"][0]["virusScanResult"] = "Pending"
        with self.assertRaises(ValueError):
            select_file(data, DownloadRequest(version_id=1, file_id=9, expected_sha256="a" * 64), 1000000)
