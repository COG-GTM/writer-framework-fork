import httpx
import pytest
from writer.keyvalue_storage import InvalidKeyError, KeyValueStorage, validate_key


@pytest.fixture
def storage_and_requests(monkeypatch):
    monkeypatch.setenv("WRITER_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("WRITER_API_KEY", "test-key")
    monkeypatch.setenv("WRITER_APP_ID", "agent-1")
    monkeypatch.setenv("WRITER_ORG_ID", "org-1")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": "value", "keys": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return KeyValueStorage(client=client), requests


@pytest.mark.parametrize("key", ["my-key", "wf-journal-a-1700000000000", "user_42", "a.b", "with space"])
def test_validate_key_accepts_regular_keys(key):
    assert validate_key(key) == key


@pytest.mark.parametrize(
    "key",
    ["", ".", "..", "../agent_secret/vault", "a/b", "a\\b", "a?b=1", "a#b", "a..b", "a\nb", None, 1],
)
def test_validate_key_rejects_unsafe_keys(key):
    with pytest.raises(InvalidKeyError):
        validate_key(key)


@pytest.mark.parametrize("key", ["../agent_secret/vault", "..", "a/b", "a?b", "a#b"])
def test_storage_never_sends_unsafe_keys(storage_and_requests, key):
    storage, requests = storage_and_requests
    with pytest.raises(InvalidKeyError):
        storage.delete(key)
    with pytest.raises(InvalidKeyError):
        storage.get(key, "data")
    with pytest.raises(InvalidKeyError):
        storage.save(key, {"x": 1})
    assert requests == []


def test_storage_url_encodes_keys(storage_and_requests):
    storage, requests = storage_and_requests
    storage.delete("with space%")
    storage.get("wf-journal-a-1", "data")
    assert requests[0].method == "DELETE"
    assert requests[0].url.raw_path == b"/v1/agent_data/with%20space%25"
    assert requests[1].url.raw_path == b"/v1/agent_data/wf-journal-a-1"
