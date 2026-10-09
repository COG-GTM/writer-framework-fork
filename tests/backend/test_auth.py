import fastapi
import fastapi.testclient
import pytest
import writer.serve
from writer import auth

from tests.backend import test_basicauth_dir


def _basicauth_app(callback=None):
    app = fastapi.FastAPI()

    @app.get("/protected")
    def protected():
        return {"ok": True}

    _auth = auth.BasicAuth(login="admin", password="s3cret", delay_after_failure=0, block_user_after_failure=False)
    _auth.register(app, callback=callback)
    return app


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

    def test_basicauth_with_callback_should_reject_wrong_password(self):
        calls = []
        app = _basicauth_app(callback=lambda request, session_id, userinfo: calls.append(userinfo))
        with fastapi.testclient.TestClient(app) as client:
            res = client.get("/protected", auth=("admin", "anything"))
            assert res.status_code == 401
            assert calls == []

    def test_basicauth_with_callback_should_reject_wrong_login(self):
        calls = []
        app = _basicauth_app(callback=lambda request, session_id, userinfo: calls.append(userinfo))
        with fastapi.testclient.TestClient(app) as client:
            res = client.get("/protected", auth=("root", "s3cret"))
            assert res.status_code == 401
            assert calls == []

    def test_basicauth_with_callback_should_call_callback_after_valid_credentials(self):
        calls = []
        app = _basicauth_app(callback=lambda request, session_id, userinfo: calls.append(userinfo))
        with fastapi.testclient.TestClient(app) as client:
            res = client.get("/protected", auth=("admin", "s3cret"))
            assert res.status_code == 200
            assert calls == [{"username": "admin"}]

    def test_basicauth_callback_can_still_reject_valid_credentials(self):
        def deny(request, session_id, userinfo):
            raise auth.Unauthorized(status_code=403, message="Forbidden")

        app = _basicauth_app(callback=deny)
        with fastapi.testclient.TestClient(app) as client:
            res = client.get("/protected", auth=("admin", "s3cret"))
            assert res.status_code == 403

    def test_basicauth_without_callback_should_reject_wrong_password(self):
        app = _basicauth_app()
        with fastapi.testclient.TestClient(app) as client:
            assert client.get("/protected", auth=("admin", "wrong")).status_code == 401
            assert client.get("/protected", auth=("admin", "s3cret")).status_code == 200

    @pytest.mark.parametrize("header", [
        "Basic !!!not-base64!!!",
        "Basic YWRtaW4=",  # "admin" without a ':' separator
        "Basic /w==",  # not valid UTF-8
    ])
    def test_basicauth_should_reject_malformed_credentials(self, header: str):
        app = _basicauth_app(callback=lambda request, session_id, userinfo: None)
        with fastapi.testclient.TestClient(app) as client:
            res = client.get("/protected", headers={"Authorization": header})
            assert res.status_code == 401

    def test_basicauth_should_reject_everyone_when_password_is_not_configured(self):
        app = fastapi.FastAPI()
        app.get("/protected")(lambda: {"ok": True})
        auth.BasicAuth(login="admin", password="", delay_after_failure=0).register(app)
        with fastapi.testclient.TestClient(app) as client:
            assert client.get("/protected", auth=("admin", "")).status_code == 401

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
