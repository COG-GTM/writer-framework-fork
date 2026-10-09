import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import fastapi
import fastapi.testclient
import pytest
import writer.serve
from writer import auth
from writer.ss_types import AppProcessServerResponse

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


class FakeAppRunner:

    def __init__(self, status: str = "ok", session_id: str = "a" * 64):
        self.status = status
        self.session_id = session_id
        self.init_payloads = []
        self.userinfo = {}

    async def init_session(self, payload):
        self.init_payloads.append(payload)
        if self.status != "ok":
            return AppProcessServerResponse(status=self.status, payload=None)
        return AppProcessServerResponse(status="ok", payload=SimpleNamespace(sessionId=self.session_id))

    def set_userinfo(self, session_id, userinfo):
        self.userinfo[session_id] = userinfo


def _oidc_client(app_runner: FakeAppRunner, **oidc_kwargs):
    asgi_app = fastapi.FastAPI()
    asgi_app.state.app_runner = app_runner

    @asgi_app.get("/")
    def protected():
        return {"ok": True}

    oidc = auth.Oidc(
        client_id="client",
        client_secret="secret",
        host_url="http://testserver",
        url_authorize="https://idp.example.com/authorize",
        url_oauthtoken="https://idp.example.com/token",
        **oidc_kwargs,
    )
    oidc.register(asgi_app)
    oidc.authlib = MagicMock()
    oidc.authlib.create_authorization_url.return_value = ("https://idp.example.com/authorize?state=x", "x")
    client = fastapi.testclient.TestClient(asgi_app, follow_redirects=False)
    return oidc, client


class TestOidc:
    forged_session_id = "c13a280fe17ec663047ec14de15cd93ad686fecf5f9a4dbf262d3a86de8cb577"

    def test_middleware_redirects_anonymous_user_to_idp(self):
        _, client = _oidc_client(FakeAppRunner())
        res = client.get("/")
        assert res.status_code == 307
        assert res.headers["location"].startswith("https://idp.example.com/authorize")

    def test_middleware_rejects_forged_session_cookie(self):
        _, client = _oidc_client(FakeAppRunner())
        res = client.get("/", cookies={"session": self.forged_session_id})
        assert res.status_code == 307
        assert res.headers["location"].startswith("https://idp.example.com/authorize")
        assert 'session=""' in res.headers["set-cookie"]

    def test_middleware_rejects_forged_cookie_on_api_init(self):
        app_runner = FakeAppRunner()
        _, client = _oidc_client(app_runner)
        res = client.post("/api/init", cookies={"session": self.forged_session_id}, json={})
        assert res.status_code == 307
        assert app_runner.init_payloads == []

    def test_callback_issues_server_generated_session(self):
        app_runner = FakeAppRunner(session_id="b" * 64)
        oidc, client = _oidc_client(app_runner)

        res = client.get("/authorize?code=abc&state=x", cookies={"session": self.forged_session_id})

        assert res.status_code == 307
        assert res.headers["location"] == "/"
        assert app_runner.init_payloads[0].proposedSessionId is None
        assert client.cookies.get("session") == "b" * 64
        assert "httponly" in res.headers["set-cookie"].lower()
        assert "samesite=lax" in res.headers["set-cookie"].lower()
        assert oidc.is_session_issued("b" * 64)
        assert not oidc.is_session_issued(self.forged_session_id)

        res = client.get("/")
        assert res.status_code == 200

    def test_callback_does_not_issue_session_when_app_rejects_it(self):
        oidc, client = _oidc_client(FakeAppRunner(status="error"))

        res = client.get("/authorize?code=abc&state=x")

        assert res.status_code == 403
        assert "session" not in client.cookies
        assert oidc.issued_sessions == {}

    def test_issued_session_expires(self):
        oidc, client = _oidc_client(FakeAppRunner(session_id="d" * 64), session_max_age_seconds=60)
        client.get("/authorize?code=abc&state=x")
        oidc.issued_sessions["d" * 64] = time.time() - 1

        res = client.get("/", cookies={"session": "d" * 64})

        assert res.status_code == 307
        assert "d" * 64 not in oidc.issued_sessions
