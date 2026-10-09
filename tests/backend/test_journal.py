from unittest.mock import ANY

import fastapi
import fastapi.testclient
import pytest
import writer.keyvalue_storage
import writer.serve
import writer.vault
from writer import journal
from writer.app_runner import AppRunner
from writer.ss_types import EventRequest, WriterEvent

from tests.backend import test_app_dir
from tests.backend.fixtures.app_runner_fixtures import init_app_session


class TestJournal:
    proposed_session_id = "c13a280fe17ec663047ec14de15cd93ad686fecf5f9a4dbf262d3a86de8cb577"

    def test_api_entry(self, mock_kv_storage):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        blueprint_id = "m4gycroojx6am4cq"

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream(
                "POST",
                f"/private/api/blueprint/{blueprint_id}",
                json={"proposedSessionId": None},
                headers={"Content-Type": "application/json"},
            ) as response:
                assert response.status_code == 200

        assert len(mock_kv_storage._data_storage) == 1
        entry = mock_kv_storage._data_storage.values()[0]
        assert entry == {
            "timestamp": ANY,
            "instanceType": "agent",
            "blueprintId": "m4gycroojx6am4cq",
            "trigger": {
                "event": "wf-run-blueprint-via-api",
                "payload": journal.OMITTED_PAYLOAD,
                "component": {"type": "block", "id": "qfqpqmjdpzuu8fe9", "title": "API alias"},
                "type": "API",
            },
            "blockOutputs": {
                "qfqpqmjdpzuu8fe9": {
                    "component": {
                        "type": "blueprints_apitrigger",
                        "id": "qfqpqmjdpzuu8fe9",
                        "title": "API alias",
                        "category": "Triggers",
                    },
                    "executions": [
                        {
                            "result": journal.OMITTED_PAYLOAD,
                            "outcome": "trigger",
                            "startedAt": ANY,
                            "executionTimeInSeconds": ANY,
                        }
                    ],
                },
                "pa448833kc2pis3a": {
                    "component": {
                        "type": "blueprints_logmessage",
                        "id": "pa448833kc2pis3a",
                        "title": "Log message",
                        "category": "Other",
                    },
                    "executions": [
                        {
                            "result": "AAA",
                            "outcome": "success",
                            "startedAt": ANY,
                            "executionTimeInSeconds": ANY,
                        }
                    ],
                },
            },
            "isRunable": True,
            "result": "success",
        }

    def test_cron_entry(self, mock_kv_storage):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        blueprint_id = "m4gycroojx6am4cq"
        branch_id = "3abex827umkt4tuo"

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream(
                "POST",
                f"/private/api/blueprint/{blueprint_id}?branch_id={branch_id}",
                json={"proposedSessionId": None},
                headers={"Content-Type": "application/json"},
            ) as response:
                assert response.status_code == 200

        assert len(mock_kv_storage._data_storage) == 1
        entry = mock_kv_storage._data_storage.values()[0]
        assert entry == {
            "timestamp": ANY,
            "instanceType": "agent",
            "blueprintId": "m4gycroojx6am4cq",
            "trigger": {
                "event": "wf-run-blueprint-via-api",
                "payload": journal.OMITTED_PAYLOAD,
                "component": {
                    "type": "block",
                    "id": "3abex827umkt4tuo",
                    "title": "my cron trigger",
                },
                "type": "Cron",
            },
            "blockOutputs": ANY,
            "isRunable": True,
            "result": "success",
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("setup_app_runner")
    async def test_ui_entry(self, setup_app_runner, mock_kv_storage):
        ar: AppRunner
        with setup_app_runner(test_app_dir, "edit", load=True) as ar:
            await init_app_session(ar, session_id=self.proposed_session_id)

            ev_req = EventRequest(
                type="event",
                payload=WriterEvent(
                    type="wf-click",
                    instancePath=[
                        {"componentId": "root", "instanceNumber": 0},
                        {
                            "componentId": "bb4d0e86-619e-4367-a180-be28ab6059f4",
                            "instanceNumber": 0,
                        },
                        {"componentId": "ud24upgqyxrjmh9q", "instanceNumber": 0},
                    ],
                    payload={},
                ),
            )

            await ar.dispatch_message(self.proposed_session_id, ev_req)
            assert len(mock_kv_storage._data_storage) == 1
            entry = mock_kv_storage._data_storage.values()[0]
            assert entry == {
                "timestamp": ANY,
                "instanceType": "editor",
                "blueprintId": "m4gycroojx6am4cq",
                "trigger": {
                    "event": "wf-click",
                    "payload": {"ctrl_key": False, "shift_key": False, "meta_key": False},
                    "component": {"type": "block", "id": "kiwqzy0ftd62y912", "title": "UI Trigger"},
                    "type": "UI",
                },
                "blockOutputs": ANY,
                "isRunable": True,
                "result": "success",
            }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("setup_app_runner")
    async def test_ui_entry_return_value(self, setup_app_runner, mock_kv_storage):
        ar: AppRunner
        with setup_app_runner(test_app_dir, "run", load=True) as ar:
            await init_app_session(ar, session_id=self.proposed_session_id)

            ev_req = EventRequest(
                type="event",
                payload=WriterEvent(
                    type="wf-click",
                    instancePath=[
                        {"componentId": "root", "instanceNumber": 0},
                        {
                            "componentId": "bb4d0e86-619e-4367-a180-be28ab6059f4",
                            "instanceNumber": 0,
                        },
                        {"componentId": "4quhc4plo1oa6vwz", "instanceNumber": 0},
                    ],
                    payload={},
                ),
            )

            await ar.dispatch_message(self.proposed_session_id, ev_req)
            assert len(mock_kv_storage._data_storage) == 1
            entry = mock_kv_storage._data_storage.values()[0]
            assert entry == {
                "timestamp": ANY,
                "instanceType": "agent",
                "blueprintId": "m4gycroojx6am4cq",
                "trigger": {
                    "event": "wf-click",
                    "payload": journal.OMITTED_PAYLOAD,
                    "component": {"type": "block", "id": "6o0ev5lml7kpb6ii", "title": ""},
                    "type": "UI",
                },
                "blockOutputs": ANY,
                "isRunable": True,
                "result": "success",
            }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("setup_app_runner")
    async def test_on_demand_branch(self, setup_app_runner, mock_kv_storage):
        ar: AppRunner
        with setup_app_runner(test_app_dir, "edit", load=True) as ar:
            await init_app_session(ar, session_id=self.proposed_session_id)

            ev_req = EventRequest(
                type="event",
                payload=WriterEvent(
                    type="wf-run-blueprint-branch",
                    isSafe=True,
                    instancePath=None,
                    handler="run_blueprint_branch",
                    payload={"branch_id": "6o0ev5lml7kpb6ii"},
                ),
            )

            await ar.dispatch_message(self.proposed_session_id, ev_req)
            assert len(mock_kv_storage._data_storage) == 1
            entry = mock_kv_storage._data_storage.values()[0]
            assert entry == {
                "timestamp": ANY,
                "instanceType": "editor",
                "blueprintId": "m4gycroojx6am4cq",
                "trigger": {
                    "event": "wf-run-blueprint-branch",
                    "payload": {},
                    "component": {"type": "block", "id": "6o0ev5lml7kpb6ii", "title": ""},
                    "type": "On demand",
                },
                "blockOutputs": ANY,
                "isRunable": True,
                "result": "success",
            }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("setup_app_runner")
    async def test_on_demand_blueprint(self, setup_app_runner, mock_kv_storage):
        ar: AppRunner
        with setup_app_runner(test_app_dir, "edit", load=True) as ar:
            await init_app_session(ar, session_id=self.proposed_session_id)

            ev_req = EventRequest(
                type="event",
                payload=WriterEvent(
                    type="wf-run-blueprint",
                    isSafe=True,
                    instancePath=None,
                    handler="run_blueprint_by_id",
                    payload={"blueprint_id": "m4gycroojx6am4cq"},
                ),
            )

            await ar.dispatch_message(self.proposed_session_id, ev_req)
            assert len(mock_kv_storage._data_storage) == 1
            entry = mock_kv_storage._data_storage.values()[0]
            assert entry == {
                "timestamp": ANY,
                "instanceType": "editor",
                "blueprintId": "m4gycroojx6am4cq",
                "trigger": {
                    "event": "wf-run-blueprint",
                    "payload": {},
                    "component": {
                        "type": "blueprint",
                        "id": "m4gycroojx6am4cq",
                        "title": "journal",
                    },
                    "type": "On demand",
                },
                "blockOutputs": ANY,
                "isRunable": True,
                "result": "success",
            }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("setup_app_runner")
    async def test_on_demand_blueprint_error(self, setup_app_runner, mock_kv_storage):
        ar: AppRunner
        with setup_app_runner(test_app_dir, "edit", load=True) as ar:
            await init_app_session(ar, session_id=self.proposed_session_id)
            ev_req = EventRequest(
                type="event",
                payload=WriterEvent(
                    type="wf-run-blueprint",
                    isSafe=True,
                    instancePath=None,
                    handler="run_blueprint_by_id",
                    payload={"blueprint_id": "n5tm1c8il2kpzttw"},
                ),
            )

            await ar.dispatch_message(self.proposed_session_id, ev_req)
            assert len(mock_kv_storage._data_storage) == 1
            entry = mock_kv_storage._data_storage.values()[0]
            assert entry == {
                "timestamp": ANY,
                "instanceType": "editor",
                "blueprintId": "n5tm1c8il2kpzttw",
                "trigger": {
                    "event": "wf-run-blueprint",
                    "payload": {},
                    "component": {
                        "type": "blueprint",
                        "id": "n5tm1c8il2kpzttw",
                        "title": "THROW ERROR",
                    },
                    "type": "On demand",
                },
                "blockOutputs": ANY,
                "isRunable": True,
                "result": "error",
            }

    def test_api_entry_records_payload_when_opted_in(self, mock_kv_storage, monkeypatch):
        monkeypatch.setenv(journal.RECORD_PAYLOADS_ENV_VAR, "1")
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        blueprint_id = "m4gycroojx6am4cq"

        with fastapi.testclient.TestClient(asgi_app) as client:
            with client.stream(
                "POST",
                f"/private/api/blueprint/{blueprint_id}",
                json={"proposedSessionId": None},
                headers={"Content-Type": "application/json"},
            ) as response:
                assert response.status_code == 200

        entry = mock_kv_storage._data_storage.values()[0]
        assert entry["trigger"]["payload"] == {"proposedSessionId": None}
        assert entry["blockOutputs"]["qfqpqmjdpzuu8fe9"]["executions"][0]["result"] == {"proposedSessionId": None}


class TestJournalRedaction:

    def _record(self) -> journal.JournalRecord:
        record = journal.JournalRecord.__new__(journal.JournalRecord)
        record.is_runable = True
        return record

    def test_sensitive_keys_are_redacted(self):
        http_result = {
            "request": {
                "url": "https://api.example.com/items",
                "headers": {
                    "Authorization": "Bearer abc123",
                    "x-api-key": "k-1",
                    "Cookie": "sid=1",
                    "Proxy-Authorization": "Basic Zm9v",
                    "Accept": "application/json",
                },
                "body": "{}",
            },
            "headers": {"Set-Cookie": "sid=2", "content-type": "application/json"},
            "status_code": 200,
            "body": {"access_token": "tok", "client_secret": "cs", "password": "p", "items": [1]},
        }

        sanitized = self._record()._sanitize_data(http_result)

        assert sanitized["request"]["headers"] == {
            "Authorization": journal.REDACTED,
            "x-api-key": journal.REDACTED,
            "Cookie": journal.REDACTED,
            "Proxy-Authorization": journal.REDACTED,
            "Accept": "application/json",
        }
        assert sanitized["headers"] == {"Set-Cookie": journal.REDACTED, "content-type": "application/json"}
        assert sanitized["body"] == {
            "access_token": journal.REDACTED,
            "client_secret": journal.REDACTED,
            "password": journal.REDACTED,
            "items": [1],
        }
        assert sanitized["status_code"] == 200

    def test_vault_values_are_masked_everywhere(self, monkeypatch):
        monkeypatch.setattr(writer.vault.writer_vault, "secrets", {"API": "sk-live-123456", "nested": {"pw": "hunter22"}, "short": "ab"})
        data = {
            "url": "https://api.example.com/?key=sk-live-123456",
            "stdout": ["logged hunter22 by mistake"],
            "x-custom": "Token sk-live-123456",
            "note": "ab stays",
        }

        sanitized = self._record()._sanitize_data(data, journal.get_vault_secret_values())

        assert sanitized == {
            "url": f"https://api.example.com/?key={journal.REDACTED}",
            "stdout": [f"logged {journal.REDACTED} by mistake"],
            "x-custom": f"Token {journal.REDACTED}",
            "note": "ab stays",
        }

    def test_non_json_values_are_sanitized_after_serialization(self):
        sanitized = self._record()._sanitize_data({"pair": ("a", {"token": "t"})})
        assert sanitized == {"pair": ["a", {"token": journal.REDACTED}]}

    @pytest.mark.parametrize("key", ["Authorization", "X-API-Key", "api_key", "OPENAI_API_KEY", "refresh_token", "Set-Cookie", "clientSecret"])
    def test_is_sensitive_key(self, key):
        assert journal.is_sensitive_key(key)

    @pytest.mark.parametrize("key", ["Accept", "content-type", "max_tokens", "status_code", "body", 1])
    def test_is_not_sensitive_key(self, key):
        assert not journal.is_sensitive_key(key)


class TestJournalDataRoutes:
    local_origin = {"Origin": "http://localhost:4005"}

    @pytest.fixture
    def kv(self, mock_kv_storage, monkeypatch):
        monkeypatch.setattr(writer.keyvalue_storage, "writer_kv_storage", mock_kv_storage)
        mock_kv_storage.save("wf-journal-a-1", {"result": "success"})
        mock_kv_storage.save("wf-init-logs-a-1", {"stdout": "hi"})
        mock_kv_storage.save("customer-record", {"email": "user@example.com"})
        return mock_kv_storage

    def test_retrieve_rejected_in_run_mode(self, kv):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/data/retrieve", json={"key_contains": "wf-journal-"}, headers=self.local_origin)
        assert res.status_code == 403

    def test_delete_rejected_in_run_mode(self, kv):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "run")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/data/delete", json={"keys": ["wf-journal-a-1"]}, headers=self.local_origin)
        assert res.status_code == 403
        assert "wf-journal-a-1" in kv._data_storage

    def test_retrieve_rejects_foreign_origin_in_edit_mode(self, kv):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            res = client.post("/api/data/retrieve", json={}, headers={"Origin": "https://evil.example.com"})
        assert res.status_code == 403

    def test_retrieve_only_returns_journal_keys_in_edit_mode(self, kv):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            all_res = client.post("/api/data/retrieve", json={}, headers=self.local_origin)
            journal_res = client.post("/api/data/retrieve", json={"key_contains": "wf-journal-"}, headers=self.local_origin)
        assert all_res.status_code == 200
        assert all_res.json()["result"] == {
            "wf-journal-a-1": {"result": "success"},
            "wf-init-logs-a-1": {"stdout": "hi"},
        }
        assert journal_res.json()["result"] == {"wf-journal-a-1": {"result": "success"}}

    def test_delete_only_accepts_journal_keys_in_edit_mode(self, kv):
        asgi_app = writer.serve.get_asgi_app(test_app_dir, "edit")
        with fastapi.testclient.TestClient(asgi_app) as client:
            bad = client.post("/api/data/delete", json={"keys": ["wf-journal-a-1", "customer-record"]}, headers=self.local_origin)
            assert bad.status_code == 400
            assert "customer-record" in kv._data_storage
            assert "wf-journal-a-1" in kv._data_storage

            ok = client.post("/api/data/delete", json={"keys": ["wf-journal-a-1", "wf-init-logs-a-1"]}, headers=self.local_origin)
        assert ok.status_code == 200
        assert list(kv._data_storage.keys()) == ["customer-record"]
