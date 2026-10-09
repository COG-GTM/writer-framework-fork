from unittest.mock import MagicMock

import pytest
from writer.keyvalue_storage import KeyValueStorage


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("WRITER_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("WRITER_API_KEY", "test-key")
    monkeypatch.setenv("WRITER_APP_ID", "agent")
    monkeypatch.setenv("WRITER_ORG_ID", "org")
    client = MagicMock()
    return KeyValueStorage(client=client), client


@pytest.mark.parametrize("key", [
    "../agent_secret/NAME",
    "a/b",
    "..",
    "a?b=c",
    "a#b",
    "a\\b",
    "",
])
def test_rejects_unsafe_keys(storage, key):
    kv, client = storage
    with pytest.raises(ValueError):
        kv.delete(key)
    with pytest.raises(ValueError):
        kv.get(key, "data")
    with pytest.raises(ValueError):
        kv.save(key, {"x": 1})
    client.delete.assert_not_called()
    client.get.assert_not_called()
    client.post.assert_not_called()
    client.put.assert_not_called()


def test_rejects_unknown_type(storage):
    kv, client = storage
    with pytest.raises(ValueError):
        kv.get("key", "other")  # type: ignore[arg-type]
    client.get.assert_not_called()


def test_encodes_key_in_url(storage):
    kv, client = storage
    kv.delete("wf journal:1")
    assert client.delete.call_args.kwargs["url"] == "https://api.example.com/v1/agent_data/wf%20journal%3A1"
    kv.get("wf-journal-1", "data")
    assert client.get.call_args.kwargs["url"] == "https://api.example.com/v1/agent_data/wf-journal-1"
