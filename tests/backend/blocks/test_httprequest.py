import json

import httpx
import pytest
from writer.blocks.httprequest import HTTPRequest


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


VAULT_SECRET = "vault-s3cr3t/value+1"
ENV_SECRET = "env-secret-token-42"


def _echo_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={
            "Content-Type": "application/json",
            "Set-Cookie": "session=abc123",
            "X-Echo": request.headers.get("X-Custom", ""),
        },
        json={"ok": True},
    )


def _mock_client(block, monkeypatch):
    monkeypatch.setattr(
        block,
        "acquire_httpx_client",
        lambda: block.create_httpx_client(transport=httpx.MockTransport(_echo_handler)),
    )


def test_request_secrets_are_redacted_from_result_and_logs(session, runner, monkeypatch):
    monkeypatch.setenv("TEST_HTTP_TOKEN", ENV_SECRET)
    component = session.add_fake_component(
        {
            "url": "https://api.example.com/items?key=@{vault.API_KEY}",
            "method": "POST",
            "headers": json.dumps(
                {
                    "Authorization": "Bearer @{vault.API_KEY}",
                    "X-API-Key": "@{$TEST_HTTP_TOKEN}",
                    "X-Custom": "prefix-@{vault.API_KEY}",
                    "Accept": "application/json",
                }
            ),
            "bodyType": "JSON",
            "body": '{"token": "@{$TEST_HTTP_TOKEN}", "name": "duck"}',
        }
    )
    block = HTTPRequest(component, runner, {"vault": {"API_KEY": VAULT_SECRET}})
    _mock_client(block, monkeypatch)
    block.run()

    assert block.outcome == "success"
    request = block.result["request"]
    assert request["headers"]["authorization"] == "[REDACTED]"
    assert request["headers"]["x-api-key"] == "[REDACTED]"
    assert request["headers"]["x-custom"] == "prefix-[REDACTED]"
    assert request["headers"]["accept"] == "application/json"
    assert json.loads(request["body"]) == {"token": "[REDACTED]", "name": "duck"}
    assert block.result["headers"]["set-cookie"] == "[REDACTED]"
    assert block.result["headers"]["x-echo"] == "prefix-[REDACTED]"
    assert block.result["body"] == {"ok": True}

    logged = json.dumps(block.execution_environment["httpx_requests"])
    serialized_result = json.dumps(block.result)
    for leaked in (VAULT_SECRET, ENV_SECRET, "session=abc123"):
        assert leaked not in serialized_result
        assert leaked not in logged
    assert "vault-s3cr3t%2Fvalue%2B1" not in serialized_result + logged


def test_request_without_secrets_is_unchanged(session, runner, monkeypatch):
    component = session.add_fake_component(
        {
            "url": "https://api.example.com/items",
            "headers": '{"X-Custom": "plain"}',
        }
    )
    block = HTTPRequest(component, runner, {})
    _mock_client(block, monkeypatch)
    block.run()

    assert block.outcome == "success"
    assert block.result["request"]["url"] == "https://api.example.com/items"
    assert block.result["request"]["headers"]["x-custom"] == "plain"
    assert block.result["headers"]["x-echo"] == "plain"
