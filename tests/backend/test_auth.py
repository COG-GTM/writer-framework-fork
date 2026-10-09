import json
from urllib.parse import parse_qs, parse_qsl, urlparse

import fastapi
import fastapi.testclient
import pytest
import requests
from authlib.oauth2.rfc7636 import create_s256_code_challenge
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
        self.userinfos = {}

    async def init_session(self, payload):
        pass

    def set_userinfo(self, session_id: str, userinfo: dict) -> None:
        self.userinfos[session_id] = userinfo


class _FakeIdentityProvider:

    def __init__(self, token_response=None):
        self.token_response = token_response or {"access_token": "token", "token_type": "Bearer"}
        self.token_requests = []

    def request(self, session, method, url, data=None, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        if url == "https://idp.example.com/token":
            self.token_requests.append(dict(parse_qsl(data)))
            response._content = json.dumps(self.token_response).encode()
        elif url == "https://idp.example.com/userinfo":
            response._content = json.dumps({"email": "user@example.com"}).encode()
        else:
            raise AssertionError(f"unexpected request {method} {url}")
        return response


@pytest.fixture
def idp(monkeypatch):
    provider = _FakeIdentityProvider()
    monkeypatch.setattr(requests.Session, "request", provider.request)
    return provider


def _oidc_client():
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
    return fastapi.testclient.TestClient(asgi_app, base_url="https://app.example.com"), asgi_app


def _start_login(client):
    res = client.get("/api/protected", follow_redirects=False)
    assert res.status_code == 307
    query = parse_qs(urlparse(res.headers["location"]).query)
    return res, query


class TestOidcLoginState:

    def test_redirect_to_identity_provider_should_bind_state_and_pkce_to_browser(self):
        client, _ = _oidc_client()
        with client:
            res, query = _start_login(client)
            state = query["state"][0]

            assert res.headers["location"].startswith("https://idp.example.com/authorize")
            assert query["code_challenge_method"] == ["S256"]
            assert query["code_challenge"] == [create_s256_code_challenge(res.cookies[f"oidc_login_{state}"])]

            login_cookies = [c for c in res.headers.get_list("set-cookie") if c.startswith("oidc_")]
            assert len(login_cookies) == 1
            cookie = login_cookies[0]
            assert cookie.startswith(f"oidc_login_{state}=")
            assert "HttpOnly" in cookie
            assert "Secure" in cookie
            assert "SameSite=lax" in cookie
            assert "Path=/authorize" in cookie
            assert "Max-Age=600" in cookie

    def test_each_login_should_get_a_fresh_state(self):
        client, _ = _oidc_client()
        with client:
            _, first = _start_login(client)
            _, second = _start_login(client)
            assert first["state"] != second["state"]

    def test_callback_should_exchange_code_when_state_matches(self, idp):
        client, asgi_app = _oidc_client()
        with client:
            res, query = _start_login(client)
            state = query["state"][0]
            code_verifier = res.cookies[f"oidc_login_{state}"]

            res = client.get(f"/authorize?code=abc&state={state}", follow_redirects=False)

            assert res.status_code == 307
            assert res.headers["location"] == "/"
            session_id = res.cookies["session"]
            assert asgi_app.state.app_runner.userinfos[session_id] == {"email": "user@example.com"}
            assert idp.token_requests[0]["code"] == "abc"
            assert idp.token_requests[0]["code_verifier"] == code_verifier
            assert f"oidc_login_{state}" not in client.cookies

    def test_parallel_logins_should_each_complete(self, idp):
        """
        Two tabs starting a login must not invalidate each other's pending sign-in.
        """
        client, _ = _oidc_client()
        with client:
            res_a, query_a = _start_login(client)
            res_b, query_b = _start_login(client)
            state_a, state_b = query_a["state"][0], query_b["state"][0]
            verifier_a = res_a.cookies[f"oidc_login_{state_a}"]
            verifier_b = res_b.cookies[f"oidc_login_{state_b}"]

            res = client.get(f"/authorize?code=code-a&state={state_a}", follow_redirects=False)
            assert res.status_code == 307
            assert idp.token_requests[-1]["code_verifier"] == verifier_a
            assert f"oidc_login_{state_a}" not in client.cookies
            assert f"oidc_login_{state_b}" in client.cookies

            client.cookies.delete("session")
            res = client.get(f"/authorize?code=code-b&state={state_b}", follow_redirects=False)
            assert res.status_code == 307
            assert idp.token_requests[-1]["code_verifier"] == verifier_b

    def test_callback_should_reject_code_without_login_state_cookie(self, idp):
        """
        Login CSRF: the attacker sends the victim a link carrying the attacker's own authorization code.
        """
        client, _ = _oidc_client()
        with client:
            res = client.get("/authorize?code=attacker-code&state=attacker-state", follow_redirects=False)

            assert res.status_code == 400
            assert "session" not in res.cookies
            assert idp.token_requests == []

    def test_callback_should_reject_mismatching_state(self, idp):
        client, _ = _oidc_client()
        with client:
            _, query = _start_login(client)
            state = query["state"][0]

            res = client.get("/authorize?code=attacker-code&state=attacker-state", follow_redirects=False)

            assert res.status_code == 400
            assert "session" not in res.cookies
            assert idp.token_requests == []
            assert f"oidc_login_{state}" in client.cookies

    def test_callback_should_reject_missing_state_parameter(self, idp):
        client, _ = _oidc_client()
        with client:
            _start_login(client)

            res = client.get("/authorize?code=attacker-code", follow_redirects=False)

            assert res.status_code == 400
            assert "session" not in res.cookies
            assert idp.token_requests == []

    def test_callback_should_reject_code_refused_by_identity_provider(self, idp):
        idp.token_response = {"error": "invalid_grant"}
        client, _ = _oidc_client()
        with client:
            _, query = _start_login(client)
            state = query["state"][0]

            res = client.get(f"/authorize?code=abc&state={state}", follow_redirects=False)

            assert res.status_code == 401
            assert "session" not in res.cookies
            assert f"oidc_login_{state}" not in client.cookies
