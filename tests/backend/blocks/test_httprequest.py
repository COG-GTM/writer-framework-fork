import ipaddress
import json

import httpx
import pytest
from writer.blocks import egress
from writer.blocks.httprequest import HTTPRequest


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        egress, "resolve_host", lambda host, port: [ipaddress.ip_address("93.184.215.14")]
    )


class FakeRequest:
    def __init__(self):
        self.body = "requestbody"
        self.headers = {"Content-Type": "application/fake"}
        self.url = "https://www.example.com"
        self.content = "requestbody".encode("utf-8")


class FakeResponse:
    def __init__(self, status_code=200, ok=True, headers={}, text=None):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.json = lambda: json.loads(text)
        self.request = FakeRequest()
        self.content = "requestbody".encode("utf-8")
        self.is_success = ok


def fake_request(_, method, url, headers={}, content="", **kwargs):
    # First argument omitted to mimick `self`
    # in the signature of httpx.Client.request
    if not headers.get("TestHeader", "not-a-sec-ret"):
        raise RuntimeError("Test header not present.")
    if method == "GET" and url == "https://www.duck.com":
        return FakeResponse(headers={"Content-Type": "text/plain"}, text="Ducks are birds.")
    if method == "POST" and url == "https://www.elephant.com":
        return FakeResponse(
            headers={"Content-Type": "application/json"},
            text='{ "elephant_name": "Momo", "request_body": "' + content + '" }',
        )
    if method == "POST" and url == "https://www.elephant.com/history":
        return FakeResponse(
            status_code=404,
            ok=False,
            headers={"Content-Type": "application/json"},
            text='{ "error_message": "Page not found." }',
        )

    raise httpx.ConnectError("Connection error")


@pytest.mark.explicit
def test_actual_request(session, runner):
    component = session.add_fake_component({"url": "https://www.example.com"})
    block = HTTPRequest(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert block.result.get("headers") is not None


@pytest.mark.explicit
def test_actual_failing_request(session, runner):
    component = session.add_fake_component(
        {"url": "https://www.site-that-does-not-exist-3017673369.com"}
    )
    block = HTTPRequest(component, runner, {})
    with pytest.raises(httpx.ConnectError):
        block.run()
    assert block.outcome == "connectionError"


@pytest.mark.explicit
def test_actual_request_with_bad_path(session, runner):
    component = session.add_fake_component({"url": "https://www.writer.com/3017673369"})
    block = HTTPRequest(component, runner, {})
    with pytest.raises(RuntimeError):
        block.run()
    assert block.outcome == "responseError"


def test_patched_request(session, runner, monkeypatch):
    monkeypatch.setattr("httpx.Client.request", fake_request)
    component = session.add_fake_component({"url": "https://www.duck.com"})
    block = HTTPRequest(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert block.result.get("body") == "Ducks are birds."


def test_patched_request_to_nowhere(session, runner, monkeypatch):
    monkeypatch.setattr("httpx.Client.request", fake_request)
    component = session.add_fake_component({"url": "https://www.cat.com"})
    block = HTTPRequest(component, runner, {})
    with pytest.raises(httpx.ConnectError):
        block.run()
    assert block.outcome == "connectionError"


def test_patched_request_with_json(session, runner, monkeypatch):
    monkeypatch.setattr("httpx.Client.request", fake_request)
    component = session.add_fake_component(
        {"url": "https://www.elephant.com", "method": "POST", "body": "Posting the elephant."}
    )
    block = HTTPRequest(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert block.result.get("body").get("elephant_name") == "Momo"
    assert block.result.get("body").get("request_body") == "Posting the elephant."


def test_patched_request_with_json_and_bad_path(session, runner, monkeypatch):
    monkeypatch.setattr("httpx.Client.request", fake_request)
    component = session.add_fake_component(
        {
            "url": "https://www.elephant.com/history",
            "method": "POST",
            "body": "Posting the elephant.",
        }
    )
    block = HTTPRequest(component, runner, {})
    with pytest.raises(RuntimeError):
        block.run()
    assert block.outcome == "responseError"  # due to not "ok"
    assert block.result.get("body").get("error_message") == "Page not found."


def test_patched_request_error_message_omits_response_body(session, runner, monkeypatch):
    monkeypatch.setattr("httpx.Client.request", fake_request)
    component = session.add_fake_component(
        {"url": "https://www.elephant.com/history", "method": "POST", "body": "x"}
    )
    block = HTTPRequest(component, runner, {})
    with pytest.raises(RuntimeError) as exc_info:
        block.run()
    assert str(exc_info.value) == "HTTP response with code 404."
    assert "Page not found" not in str(exc_info.value)


def capture_url(monkeypatch):
    seen = {}

    def request(_, method, url, headers={}, content="", **kwargs):
        seen["url"] = url
        return FakeResponse(headers={"Content-Type": "text/plain"}, text="ok")

    monkeypatch.setattr("httpx.Client.request", request)
    return seen


def test_templated_url_values_are_encoded(session, runner, monkeypatch):
    seen = capture_url(monkeypatch)
    component = session.add_fake_component(
        {"url": "https://api.example.com/users/@{payload.user}?q=@{payload.q}"}
    )
    block = HTTPRequest(
        component, runner, {"payload": {"user": "../admin?all=1#", "q": "a b&c=d"}}
    )
    block.run()
    assert seen["url"] == "https://api.example.com/users/..%2Fadmin%3Fall%3D1%23?q=a%20b%26c%3Dd"


def test_templated_value_cannot_change_host(session, runner, monkeypatch):
    seen = capture_url(monkeypatch)
    component = session.add_fake_component({"url": "https://@{payload}.example.com/"})
    block = HTTPRequest(component, runner, {"payload": "169.254.169.254/latest#"})
    block.run()
    url = httpx.URL(seen["url"])
    assert url.host.endswith(".example.com")
    assert url.path == "/"


def test_leading_template_provides_base_url(session, runner, monkeypatch):
    seen = capture_url(monkeypatch)
    component = session.add_fake_component({"url": "@{base}/items/@{payload}"})
    block = HTTPRequest(
        component, runner, {"base": "https://api.example.com/v1", "payload": "a/b"}
    )
    block.run()
    assert seen["url"] == "https://api.example.com/v1/items/a%2Fb"


def test_full_template_url_is_not_encoded(session, runner, monkeypatch):
    seen = capture_url(monkeypatch)
    component = session.add_fake_component({"url": "@{destination}"})
    block = HTTPRequest(component, runner, {"destination": "https://api.example.com/a?b=1&c=2"})
    block.run()
    assert seen["url"] == "https://api.example.com/a?b=1&c=2"
