import base64

import fastapi
import fastapi.testclient
import pytest
import writer.serve
from starlette.requests import Request
from writer import auth

from tests.backend import test_basicauth_dir


class TestAuth:

    def test_basicauth_authentication_module_should_ask_user_to_write_basic_auth(self):
        """
        This test verifies that a user has to authenticate when the basic auth module is active.

        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_basicauth_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/api/init")
            assert res.status_code == 401

    def test_basicauth_authentication_module_should_accept_user_using_authorization(self):
        """
        This test verifies that a user can use the application when providing basic auth credentials.

        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_basicauth_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/static/file.js", auth=("admin", "admin"))
            assert res.status_code == 200

    def test_basicauth_authentication_module_disabled_when_server_setup_hook_is_disabled(self):
        """
        This test verifies that a user bypass the authentication when server setup hook is disabled.
        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_basicauth_dir, "run", enable_server_setup=False)
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/api/init")
            assert res.status_code == 405

    @pytest.mark.parametrize("path,expected_path", [
        ("", "/"),
        ("http://localhost", "/"),
        ("http://localhost/", "/"),
        ("http://localhost/any", "/any"),
        ("http://localhost/any/", "/any/"),
        ("/any/yolo", "/any/yolo")
    ])
    def test_url_path_scenarios(self, path: str, expected_path: str):
        assert auth.urlpath(path) == expected_path

    @pytest.mark.parametrize("path,expected_path", [
        ("/", ""),
        ("/yolo", "yolo"),
        ("/yolo/", "yolo"),
        ("http://localhost", "http://localhost"),
        ("http://localhost/", "http://localhost"),
        ("http://localhost/any", "http://localhost/any"),
        ("http://localhost/any/", "http://localhost/any")
    ])
    def test_url_split_scenarios(self, path: str, expected_path: str):
        assert auth.urlstrip(path) == expected_path

    @pytest.mark.parametrize("path1,path2,expected_path", [
        ("/", "any", "/any"),
        ("", "any", "any"),
        ("/yolo", "any", "/yolo/any"),
        ("/yolo", "/any", "/yolo/any"),
        ("http://localhost", "any", "http://localhost/any"),
        ("http://localhost/", "/any", "http://localhost/any"),
        ("http://localhost/yolo", "/any", "http://localhost/yolo/any"),
    ])
    def test_urljoin_scenarios(self, path1: str, path2, expected_path: str):
        assert auth.urljoin(path1, path2) == expected_path


def _basicauth_client(**kwargs) -> fastapi.testclient.TestClient:
    kwargs.setdefault("login", "admin")
    kwargs.setdefault("password", "admin")
    kwargs.setdefault("block_user_after_failure", False)
    basic_auth = auth.BasicAuth(**kwargs)
    asgi_app = fastapi.FastAPI()

    @asgi_app.get("/ping")
    def ping():
        return {"ok": True}

    basic_auth.register(asgi_app)  # type: ignore
    client = fastapi.testclient.TestClient(asgi_app)
    client.basic_auth = basic_auth  # type: ignore
    return client


def _request(peer: str, headers: dict) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    })


class TestBasicAuthBruteForce:

    def test_valid_credentials_are_accepted(self):
        client = _basicauth_client()
        assert client.get("/ping", auth=("admin", "admin")).status_code == 200

    def test_spoofed_forwarded_headers_do_not_bypass_the_delay(self):
        client = _basicauth_client(delay_after_failure=60)

        res = client.get("/ping", auth=("admin", "wrong"), headers={"X-Forwarded-For": "10.0.0.1"})
        assert res.status_code == 401
        res = client.get("/ping", auth=("admin", "wrong"), headers={"X-Forwarded-For": "10.0.0.2"})
        assert res.status_code == 429
        res = client.get("/ping", auth=("admin", "admin"), headers={"X-Real-IP": "10.0.0.3"})
        assert res.status_code == 429

        assert list(client.basic_auth.failed_attempts._entries) == ["testclient"]

    def test_spoofed_forwarded_header_cannot_lock_out_another_client(self):
        client = _basicauth_client(delay_after_failure=60, max_failures_per_username=None)

        client.get("/ping", auth=("admin", "wrong"), headers={"X-Forwarded-For": "203.0.113.7"})

        assert "203.0.113.7" not in client.basic_auth.failed_attempts

    def test_per_username_limit_applies_across_ips(self):
        client = _basicauth_client(delay_after_failure=0, max_failures_per_username=2)

        assert client.get("/ping", auth=("admin", "wrong1")).status_code == 401
        assert client.get("/ping", auth=("admin", "wrong2")).status_code == 401
        assert client.get("/ping", auth=("admin", "admin")).status_code == 429
        assert client.get("/ping", auth=("other", "x")).status_code == 401

    def test_per_username_limit_can_be_disabled(self):
        client = _basicauth_client(delay_after_failure=0, max_failures_per_username=None)

        for _ in range(20):
            assert client.get("/ping", auth=("admin", "wrong")).status_code == 401
        assert client.get("/ping", auth=("admin", "admin")).status_code == 200
        assert len(client.basic_auth.failed_attempts_per_username) == 0

    @pytest.mark.parametrize("header", [
        "Basic !!!notbase64",
        "Basic " + base64.b64encode(b"no-colon").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:x").decode(),
    ])
    def test_malformed_basic_credentials_are_rejected(self, header):
        client = _basicauth_client(delay_after_failure=0)
        assert client.get("/ping", headers={"Authorization": header}).status_code == 401


class TestFailedAttempts:

    def test_entries_expire_after_the_window(self):
        attempts = auth.FailedAttempts(window=5)
        attempts.record("a", now=100)

        assert attempts.retry_after("a", now=102) == 3
        assert attempts.retry_after("a", now=105) == 0
        assert len(attempts) == 0

    def test_limit_counts_failures_within_window(self):
        attempts = auth.FailedAttempts(window=60, limit=3)
        attempts.record("a", now=0)
        attempts.record("a", now=10)
        assert attempts.retry_after("a", now=11) == 0

        attempts.record("a", now=20)
        assert attempts.retry_after("a", now=21) == 39
        assert attempts.retry_after("a", now=61) == 0

    def test_store_is_bounded(self):
        attempts = auth.FailedAttempts(window=3600, max_entries=100)
        for i in range(10000):
            attempts.record(f"10.0.{i // 256}.{i % 256}", now=i)

        assert len(attempts) == 100
        assert "10.0.39.15" in attempts  # most recent key is kept
        assert "10.0.0.0" not in attempts  # oldest keys are evicted


class TestClientIp:

    def test_forwarded_headers_are_ignored_without_trusted_proxies(self):
        request = _request("198.51.100.1", {"X-Forwarded-For": "10.0.0.1", "X-Real-IP": "10.0.0.2"})
        assert auth._client_ip(request) == "198.51.100.1"

    def test_forwarded_headers_are_ignored_from_untrusted_peer(self):
        request = _request("198.51.100.1", {"X-Forwarded-For": "10.0.0.1"})
        assert auth._client_ip(request, auth._parse_networks(["127.0.0.1"])) == "198.51.100.1"

    def test_rightmost_untrusted_forwarded_hop_is_used_behind_trusted_proxy(self):
        trusted = auth._parse_networks(["127.0.0.1", "10.0.0.0/8"])
        request = _request("127.0.0.1", {"X-Forwarded-For": "1.1.1.1, 203.0.113.9, 10.1.2.3"})
        assert auth._client_ip(request, trusted) == "203.0.113.9"

    def test_real_ip_is_used_behind_trusted_proxy(self):
        request = _request("10.0.0.5", {"X-Real-IP": "203.0.113.9"})
        assert auth._client_ip(request, auth._parse_networks(["10.0.0.0/8"])) == "203.0.113.9"
