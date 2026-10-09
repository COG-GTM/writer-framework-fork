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
        self.proposed_session_ids = []
        self.userinfos = {}

    async def init_session(self, payload):
        self.proposed_session_ids.append(payload.proposedSessionId)

    def set_userinfo(self, session_id: str, userinfo: dict) -> None:
        self.userinfos[session_id] = userinfo


class _FakeUserinfoResponse:

    def json(self):
        return {"email": "user@example.com"}


def _oidc_app(callback=None):
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

    @asgi_app.post("/api/init")
    async def init():
        return {"ok": True}

    @asgi_app.websocket("/api/stream")
    async def stream(websocket: fastapi.WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json({"echo": await websocket.receive_json()})
        except fastapi.WebSocketDisconnect:
            return

    oidc.register(asgi_app, callback=callback)
    oidc.authlib.fetch_token = lambda **kwargs: {"access_token": "token"}
    oidc.authlib.get = lambda url: _FakeUserinfoResponse()
    return asgi_app, oidc


class TestOidcAuth:

    def test_oidc_should_redirect_anonymous_user_to_identity_provider(self):
        asgi_app, _ = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/init", follow_redirects=False)
            assert res.status_code == 307
            assert res.headers["location"].startswith("https://idp.example.com/authorize")

    @pytest.mark.parametrize("forged_session", ["a" * 64, "anything"])
    def test_oidc_should_reject_session_cookie_not_issued_by_callback(self, forged_session: str):
        asgi_app, _ = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", forged_session)
            res = client.post("/api/init", follow_redirects=False)
            assert res.status_code == 307
            assert res.headers["location"].startswith("https://idp.example.com/authorize")
            assert 'session=""' in res.headers["set-cookie"]

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
            assert oidc.is_session_issued(session_id)
            assert asgi_app.state.app_runner.proposed_session_ids == [session_id]
            assert asgi_app.state.app_runner.userinfos[session_id] == {"email": "user@example.com"}

            client.cookies.set("session", session_id)
            res = client.post("/api/init", follow_redirects=False)
            assert res.status_code == 200

    def test_oidc_should_not_issue_session_when_callback_rejects_user(self):
        def reject(request, session_id, userinfo):
            raise auth.Unauthorized(message="Not allowed")

        asgi_app, oidc = _oidc_app(callback=reject)
        with fastapi.testclient.TestClient(asgi_app, base_url="https://app.example.com") as client:
            res = client.get("/authorize?code=abc&state=xyz", follow_redirects=False)
            assert res.status_code == 401
            assert "session" not in res.cookies
            assert oidc.issued_sessions == {}

            rejected_session_id = asgi_app.state.app_runner.proposed_session_ids[0]
            client.cookies.set("session", rejected_session_id)
            res = client.post("/api/init", follow_redirects=False)
            assert res.status_code == 307

    def test_oidc_should_reject_expired_session(self):
        asgi_app, oidc = _oidc_app()
        session_id = "b" * 64
        oidc.issued_sessions[session_id] = 0
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", session_id)
            res = client.post("/api/init", follow_redirects=False)
            assert res.status_code == 307
            assert session_id not in oidc.issued_sessions

    def _issued_session(self, client) -> str:
        res = client.get("/authorize?code=abc&state=xyz", follow_redirects=False)
        return res.cookies["session"]

    @pytest.mark.parametrize("payload", [{"sessionId": "c" * 64}, {}, None])
    def test_oidc_stream_should_close_when_session_was_not_issued(self, payload):
        asgi_app, _ = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.websocket_connect("/api/stream") as ws:
                ws.send_json({"type": "streamInit", "trackingId": 0, "payload": payload})
                with pytest.raises(fastapi.WebSocketDisconnect) as exc:
                    ws.receive_json()
                assert exc.value.code == 1008

    def test_oidc_stream_should_accept_issued_session_and_close_once_it_expires(self):
        asgi_app, oidc = _oidc_app()
        with fastapi.testclient.TestClient(asgi_app, base_url="https://app.example.com") as client:
            session_id = self._issued_session(client)
            with client.websocket_connect("/api/stream") as ws:
                ws.send_json({"type": "streamInit", "trackingId": 0, "payload": {"sessionId": session_id}})
                assert ws.receive_json()["echo"]["type"] == "streamInit"
                ws.send_json({"type": "keepAlive", "trackingId": 1, "payload": None})
                assert ws.receive_json()["echo"]["type"] == "keepAlive"

                oidc.issued_sessions[session_id] = 0
                ws.send_json({"type": "event", "trackingId": 2, "payload": {}})
                with pytest.raises(fastapi.WebSocketDisconnect) as exc:
                    ws.receive_json()
                assert exc.value.code == 1008
