import contextlib
import http.server
import socketserver
import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import health_check  # noqa: E402


class MockHealthHandler(http.server.BaseHTTPRequestHandler):
    status_code = 200
    content_type = "application/json"
    body = b'{"status": "ok"}'

    def do_GET(self):
        self.send_response(self.status_code)
        self.send_header("Content-Type", self.content_type)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):
        return


@contextlib.contextmanager
def mock_server(status_code=200, body=b'{"status": "ok"}', content_type="application/json"):
    handler = type(
        "ConfiguredHealthHandler",
        (MockHealthHandler,),
        {
            "status_code": status_code,
            "body": body,
            "content_type": content_type,
        },
    )
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


class HealthCheckValidationTests(unittest.TestCase):
    def check_mock(self, body, content_type="application/json", status_code=200):
        with mock_server(status_code=status_code, body=body, content_type=content_type) as port:
            return health_check.check_http_service(
                "127.0.0.1",
                port,
                "/health",
                2,
                expect_json=True,
            )

    def test_rejects_empty_200_response(self):
        status, detail, code = self.check_mock(b"")

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 200)
        self.assertIn("empty response body", detail)

    def test_rejects_malformed_json_response(self):
        status, detail, code = self.check_mock(b"{not-json")

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 200)
        self.assertIn("invalid JSON response", detail)

    def test_rejects_wrong_content_type(self):
        status, detail, code = self.check_mock(b'{"status": "ok"}', content_type="text/plain")

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 200)
        self.assertIn("unexpected content type", detail)

    def test_accepts_valid_healthy_response(self):
        status, detail, code = self.check_mock(b'{"status": "ok", "uptime_seconds": 12}')

        self.assertEqual(status, "OK")
        self.assertEqual(code, 200)
        self.assertIn("status=ok", detail)

    def test_rejects_unhealthy_status_field(self):
        status, detail, code = self.check_mock(b'{"status": "down"}')

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 200)
        self.assertIn("is not healthy", detail)

    def test_http_failure_is_critical(self):
        status, detail, code = self.check_mock(b'{"status": "down"}', status_code=503)

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 503)
        self.assertIn("HTTP 503", detail)


if __name__ == "__main__":
    unittest.main()
