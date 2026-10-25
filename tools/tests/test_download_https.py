"""Real curl against a loopback HTTPS fixture; never contacts external services."""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easy_installer import download_file

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    x509 = None

BODY = bytes(range(256)) * 1024


@unittest.skipUnless(x509 is not None and shutil.which('curl'), 'requires curl and cryptography')
class CurlHTTPSTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='aaa-https-fixture-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.requests = []
        self.mode = 'range'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'AAA local fixture')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                .sign(key, hashes.SHA256()))
        self.cert_path = self.root / 'fixture.pem'
        self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = self.root / 'fixture.key'
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_GET(self):
                requested = self.headers.get('Range')
                fixture.requests.append(requested)
                if fixture.mode == 'html' and len(fixture.requests) == 1:
                    body = b'<html>temporary upstream error</html>'
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body); return
                if fixture.mode == 'short' and len(fixture.requests) == 1:
                    self.send_response(200)
                    self.send_header('Content-Length', '32768')
                    self.end_headers(); self.wfile.write(BODY[:32768]); return
                offset = int(requested.split('=')[1].split('-')[0]) if requested and fixture.mode != 'ignore' else 0
                self.send_response(206 if offset else 200)
                self.send_header('Content-Length', str(len(BODY) - offset))
                if offset: self.send_header('Content-Range', f'bytes {offset}-{len(BODY)-1}/{len(BODY)}')
                self.end_headers()
                if fixture.mode == 'interrupt' and len(fixture.requests) == 1:
                    self.wfile.write(BODY[:32768]); self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close(); return
                try:
                    self.wfile.write(BODY[offset:])
                except (ConnectionResetError, BrokenPipeError):
                    # curl deliberately closes when the fixture ignores Range.
                    if fixture.mode != 'ignore': raise

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert_path), str(key_path))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        self.addCleanup(stop)
        self.url = f'https://127.0.0.1:{server.server_port}/fixture.bin'

    def download(self):
        target = self.root / 'model.bin'
        real_popen = subprocess.Popen
        def trusted_fixture(args, **kwargs):
            # Test-only CA trust, not --insecure and never added to production settings.
            return real_popen(args[:-1] + ['--cacert', str(self.cert_path), args[-1]], **kwargs)
        with patch('download_network.subprocess.Popen', side_effect=trusted_fixture), patch('download_network.time.sleep'):
            download_file(self.url, target, lambda s: None,
                          expected_sha256=hashlib.sha256(BODY).hexdigest(), expected_size=len(BODY))
        self.assertEqual(target.read_bytes(), BODY)

    def test_resume(self):
        (self.root / 'model.bin.part').write_bytes(BODY[:4096])
        self.download()
        self.assertEqual(self.requests, ['bytes=4096-'])

    def test_ignored_range_starts_fresh(self):
        self.mode = 'ignore'
        (self.root / 'model.bin.part').write_bytes(BODY[:4096])
        self.download()
        self.assertEqual(self.requests, ['bytes=4096-', None])
        self.assertEqual(len(list(self.root.glob('*.rejected.*'))), 1)

    def test_html_rejected_then_recovered(self):
        self.mode = 'html'; self.download()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(list(self.root.glob('*.rejected.*'))), 1)

    def test_connection_interrupted_resumes_new_offset(self):
        self.mode = 'interrupt'; self.download()
        self.assertEqual(self.requests, [None, 'bytes=32768-'])

    def test_successful_short_body_resumes_without_quarantine(self):
        self.mode = 'short'; self.download()
        self.assertEqual(self.requests, [None, 'bytes=32768-'])
        self.assertFalse(list(self.root.glob('*.rejected.*')))


if __name__ == '__main__': unittest.main()
