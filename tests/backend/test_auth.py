from unittest import mock

import fastapi
import fastapi.testclient
import pytest
import writer.serve
from starlette.websockets import WebSocketDisconnect
from writer import auth

from tests.backend import test_basicauth_dir, test_oidcauth_dir

FORGED_SESSION_ID = "a" * 64


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

    def test_oidc_should_redirect_request_with_forged_session_cookie(self):
        """
        A session cookie that was not issued by the OIDC callback must not grant access.
        """
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_oidcauth_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", FORGED_SESSION_ID)
            res = client.post("/api/init", json={"proposedSessionId": None}, follow_redirects=False)
            assert res.status_code == 307
            assert res.headers["location"].startswith("https://idp.example.com/authorize")

            res = client.get("/", follow_redirects=False)
            assert res.status_code == 307

    def test_oidc_should_reject_websocket_with_forged_session_cookie(self):
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_oidcauth_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            client.cookies.set("session", FORGED_SESSION_ID)
            client.post("/api/init", json={"proposedSessionId": FORGED_SESSION_ID}, follow_redirects=False)
            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json({
                    "type": "streamInit",
                    "trackingId": 0,
                    "payload": {
                        "sessionId": FORGED_SESSION_ID
                    }
                })
                with pytest.raises(WebSocketDisconnect) as exc:
                    websocket.receive_json()
                assert exc.value.code == 1008

    def test_oidc_should_accept_session_issued_by_callback(self):
        asgi_app: fastapi.FastAPI = writer.serve.get_asgi_app(test_oidcauth_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            with mock.patch.object(auth.OAuth2Session, "fetch_token"):
                res = client.get("/authorize?code=xxx&state=yyy", follow_redirects=False)
            assert res.status_code == 307
            session_id = res.cookies.get("session")
            assert session_id is not None
            assert session_id != FORGED_SESSION_ID

            client.cookies.set("session", session_id)
            res = client.post("/api/init", json={"proposedSessionId": None}, follow_redirects=False)
            assert res.status_code == 200
            assert res.json()["sessionId"] == session_id

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
