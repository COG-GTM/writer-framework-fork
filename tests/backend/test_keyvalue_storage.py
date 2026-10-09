import httpx
import pytest
from writer.keyvalue_storage import InvalidKeyError, KeyValueStorage


@pytest.fixture
def kv_env(monkeypatch):
    monkeypatch.setenv("WRITER_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("WRITER_API_KEY", "test-key")
    monkeypatch.setenv("WRITER_APP_ID", "agent-1")
    monkeypatch.setenv("WRITER_ORG_ID", "org-1")


@pytest.fixture
def storage_and_requests(kv_env):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"key": "k", "data": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return KeyValueStorage(client=client), requests


INVALID_KEYS = [
    "../agent_secret/vault",
    "a/b",
    "a?x=1",
    "a#frag",
    "a%2Fb",
    "a b",
    "..",
    "",
]


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_keys_are_rejected_before_any_request(storage_and_requests, key):
    storage, requests = storage_and_requests

    with pytest.raises(InvalidKeyError):
        storage.delete(key)
    with pytest.raises(InvalidKeyError):
        storage.get(key, "data")
    with pytest.raises(InvalidKeyError):
        storage.get(key, "secret")
    with pytest.raises(InvalidKeyError):
        storage.save(key, {"x": 1})
    with pytest.raises(InvalidKeyError):
        storage._update(key, {"x": 1})

    assert requests == []


def test_unknown_type_is_rejected(storage_and_requests):
    storage, requests = storage_and_requests

    with pytest.raises(ValueError):
        storage.get("vault", "files/../x")  # type: ignore[arg-type]
    assert requests == []


def test_valid_key_urls(storage_and_requests):
    storage, requests = storage_and_requests

    storage.get("wf-journal-a-123", "data")
    storage.get("vault", "secret")
    storage._update("my_key-1", {"x": 1})
    storage.delete("my_key-1")

    assert [(r.method, str(r.url)) for r in requests] == [
        ("GET", "https://api.example.com/v1/agent_data/wf-journal-a-123"),
        ("GET", "https://api.example.com/v1/agent_secret/vault"),
        ("PUT", "https://api.example.com/v1/agent_data/my_key-1"),
        ("DELETE", "https://api.example.com/v1/agent_data/my_key-1"),
    ]
