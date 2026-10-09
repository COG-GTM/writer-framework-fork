import fastapi
import fastapi.testclient
import pytest
import writer.serve
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


class _FakeAppRunner:

    def __init__(self):
        self.init_payloads = []
        self.userinfos = {}

    async def init_session(self, payload):
        self.init_payloads.append(payload)

    def set_userinfo(self, session_id: str, userinfo: dict) -> None:
        self.userinfos[session_id] = userinfo


class _FakeUserinfoResponse:

    def json(self):
        return {"email": "user@example.com"}


def _oidc_app():
    oidc = auth.Oidc(
        client_id="client",
        client_secret="secret",
        host_url="https://app.example.com",
        url_authorize="https://idp.example.com/authorize",
        url_oauthtoken="https://idp.example.com/token",
        url_userinfo="https://idp.example.com/userinfo",
    )
    asgi_app = fastapi.FastAPI()
    asgi_app.state.app_runner = _FakeAppRunner()

    @asgi_app.get("/api/protected")
    async def protected():
        return {"ok": True}

    oidc.register(asgi_app)
    oidc.authlib.fetch_token = lambda **kwargs: {"access_token": "token"}
    oidc.authlib.get = lambda url: _FakeUserinfoResponse()
    return asgi_app, oidc


class TestOidcAuth:

    def test_oidc_should_redirect_anonymous_user_to_identity_provider(self):
        asgi_app, _ = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.get("/api/protected", follow_redirects=False)
            assert res.status_code == 307
            assert res.headers["location"].startswith("https://idp.example.com/authorize")

    def test_oidc_should_reject_forged_session_cookie(self):
        asgi_app, _ = _oidc_app()
        forged_session = "a" * 64
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", forged_session)
            res = client.get("/api/protected", follow_redirects=False)
            assert res.status_code == 307
            assert res.headers["location"].startswith("https://idp.example.com/authorize")

    def test_oidc_should_accept_session_issued_by_callback(self):
        asgi_app, oidc = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app, base_url="https://app.example.com") as client:
            res = client.get("/authorize?code=abc&state=xyz", follow_redirects=False)
            assert res.status_code == 307
            set_cookie = res.headers["set-cookie"]
            assert "HttpOnly" in set_cookie
            assert "Secure" in set_cookie
            assert "SameSite=lax" in set_cookie

            session_id = res.cookies["session"]
            assert session_id in oidc.issued_sessions
            assert asgi_app.state.app_runner.userinfos[session_id] == {"email": "user@example.com"}

            client.cookies.set("session", session_id)
            res = client.get("/api/protected", follow_redirects=False)
            assert res.status_code == 200

    def test_oidc_should_reject_expired_session(self):
        asgi_app, oidc = _oidc_app()
        session_id = "b" * 64
        oidc.issued_sessions[session_id] = 0
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", session_id)
            res = client.get("/api/protected", follow_redirects=False)
            assert res.status_code == 307
            assert session_id not in oidc.issued_sessions
