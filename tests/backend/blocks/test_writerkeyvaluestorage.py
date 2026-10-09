import contextlib

import pytest

from writer.blocks.writerkeyvaluestorage import WriterKeyValueStorage
from writer.ss_types import WriterConfigurationError


@pytest.fixture
def kv_store(monkeypatch, fake_client):
    calls = []

    class MockKeyValueStorage:
        def __init__(self, client=None):
            pass

        def get_data_keys(self):
            return ["my-key", "wf-journal-a-1700000000000", "wf-init-logs-e-1700000000000", "other_key"]

        def get(self, key, type_):
            calls.append(("get", key))
            return {"data": "value"}

        def save(self, key, data):
            calls.append(("save", key))
            return {"key": key}

        def delete(self, key):
            calls.append(("delete", key))
            return {"key": key}

    monkeypatch.setattr("writer.keyvalue_storage.KeyValueStorage", MockKeyValueStorage)
    monkeypatch.setattr(WriterKeyValueStorage, "acquire_httpx_client", lambda self: contextlib.nullcontext())
    return calls


def test_list_keys_hides_reserved_prefixes(session, runner, kv_store):
    component = session.add_fake_component({"action": "List keys"})
    block = WriterKeyValueStorage(component, runner, {})
    block.run()

    assert block.outcome == "success"
    assert block.result == ["my-key", "other_key"]


@pytest.mark.parametrize("action", ["Get", "Save", "Delete"])
@pytest.mark.parametrize(
    "key",
    ["wf-journal-a-1700000000000", "wf-init-logs-e-1700000000000", "WF-Journal-a-1", "wf-init-logs-"],
)
def test_reserved_keys_rejected(session, runner, kv_store, action, key):
    component = session.add_fake_component({"action": action, "key": key, "value": "x"})
    block = WriterKeyValueStorage(component, runner, {})

    with pytest.raises(WriterConfigurationError):
        block.run()

    assert block.outcome == "error"
    assert kv_store == []


@pytest.mark.parametrize("action", ["Get", "Save", "Delete"])
def test_regular_keys_allowed(session, runner, kv_store, action):
    component = session.add_fake_component({"action": action, "key": "wf-journal", "value": "x"})
    block = WriterKeyValueStorage(component, runner, {})
    block.run()

    assert block.outcome == "success"
    assert kv_store == [(action.lower(), "wf-journal")]
