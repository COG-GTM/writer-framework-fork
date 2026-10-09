import asyncio
from urllib.parse import parse_qs, urlparse

import fastapi
import fastapi.testclient
import httpx
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


class FakeOAuth2Session:
    """Stands in for authlib's OAuth2Session: the token is per-instance state, like the real one."""

    def __init__(self, **kwargs):
        self.token = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def create_authorization_url(self, url):
        return (url + "?state=xyz", "xyz")

    def fetch_token(self, url, authorization_response):
        code = parse_qs(urlparse(authorization_response).query)["code"][0]
        self.token = {"access_token": "token-" + code}
        return self.token

    def get(self, url):
        return httpx.Response(200, json={"sub": self.token["access_token"][len("token-"):]})


class BlockingAppRunner:
    """Holds every init_session until `expected` callbacks are in flight, forcing them to interleave."""

    def __init__(self, expected: int):
        self.expected = expected
        self.started = 0
        self.all_started = asyncio.Event()
        self.userinfo = {}

    async def init_session(self, payload):
        self.started += 1
        if self.started >= self.expected:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=5)

    def set_userinfo(self, session_id, userinfo):
        self.userinfo[session_id] = userinfo


class TestOidc:

    @pytest.mark.asyncio
    async def test_concurrent_callbacks_keep_their_own_userinfo(self, monkeypatch):
        """
        Two OIDC callbacks that interleave across the init_session await must each
        bind their session to the identity of their own token.
        """
        app_runner = BlockingAppRunner(expected=2)
        monkeypatch.setattr(auth, "OAuth2Session", FakeOAuth2Session)
        monkeypatch.setattr(writer.serve, "app_runner", lambda asgi_app: app_runner)

        callback_identities = {}

        def callback(request, session_id, userinfo):
            callback_identities[session_id] = userinfo["sub"]

        asgi_app = fastapi.FastAPI()
        oidc = auth.Oidc(
            client_id="client",
            client_secret="secret",
            host_url="http://localhost",
            url_authorize="https://idp.example/authorize",
            url_oauthtoken="https://idp.example/token",
            url_userinfo="https://idp.example/userinfo",
        )
        oidc.register(asgi_app, callback=callback)

        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            responses = await asyncio.gather(
                client.get("/authorize", params={"code": "alice", "state": "xyz"}),
                client.get("/authorize", params={"code": "bob", "state": "xyz"}),
            )

        sessions = {}
        for user, res in zip(["alice", "bob"], responses):
            assert res.status_code == 307
            sessions[user] = res.cookies["session"]

        assert sessions["alice"] != sessions["bob"]
        for user, session_id in sessions.items():
            assert app_runner.userinfo[session_id] == {"sub": user}
            assert callback_identities[session_id] == user
        assert oidc.authlib.token is None
