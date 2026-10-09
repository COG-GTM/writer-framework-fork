from types import SimpleNamespace

import httpx
import pytest

import writer.core
from writer import vault as vault_module
from writer.keyvalue_storage import KeyValueStorage, resolve_tenant_ids
from writer.vault import WriterVault

ENV_AGENT = "env-agent"
ENV_ORG = "env-org"
SPOOFED_HEADERS = {"x-agent-id": "victim-agent", "x-organization-id": "victim-org"}


@pytest.fixture
def kv_env(monkeypatch):
    monkeypatch.setenv("WRITER_BASE_URL", "https://writer.test")
    monkeypatch.setenv("WRITER_API_KEY", "server-key")
    monkeypatch.setenv("WRITER_APP_ID", ENV_AGENT)
    monkeypatch.setenv("WRITER_ORG_ID", ENV_ORG)
    monkeypatch.delenv("WRITER_TRUST_TENANT_HEADERS", raising=False)


def _use_session_headers(monkeypatch, headers):
    session = SimpleNamespace(headers=headers)
    monkeypatch.setattr(writer.core, "get_session", lambda: session)


def _recording_storage():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        tenant = request.headers["X-Agent-Id"]
        return httpx.Response(200, json={"data": tenant, "secret": {"tenant": tenant}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return KeyValueStorage(client=client), seen


def test_client_tenant_headers_ignored_by_default(kv_env, monkeypatch):
    _use_session_headers(monkeypatch, SPOOFED_HEADERS)
    storage, seen = _recording_storage()

    assert storage.get_agent_ids() == (ENV_AGENT, ENV_ORG)
    storage.get("some-key", "data")

    assert seen[0].headers["X-Agent-Id"] == ENV_AGENT
    assert seen[0].headers["X-Organization-Id"] == ENV_ORG
    assert seen[0].headers["Authorization"] == "Bearer server-key"


def test_client_tenant_headers_without_env_do_not_grant_access(kv_env, monkeypatch):
    monkeypatch.delenv("WRITER_APP_ID")
    monkeypatch.delenv("WRITER_ORG_ID")
    _use_session_headers(monkeypatch, SPOOFED_HEADERS)
    storage, seen = _recording_storage()

    assert not storage.is_accessible()
    with pytest.raises(ValueError):
        storage.get("some-key", "data")
    assert seen == []


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes"])
def test_tenant_headers_honoured_when_trusted(kv_env, monkeypatch, flag):
    monkeypatch.setenv("WRITER_TRUST_TENANT_HEADERS", flag)
    _use_session_headers(monkeypatch, SPOOFED_HEADERS)
    storage, seen = _recording_storage()

    storage.get("some-key", "data")

    assert seen[0].headers["X-Agent-Id"] == "victim-agent"
    assert seen[0].headers["X-Organization-Id"] == "victim-org"


@pytest.mark.parametrize("flag", ["", "0", "false", "no"])
def test_resolve_tenant_ids_untrusted_values(kv_env, monkeypatch, flag):
    monkeypatch.setenv("WRITER_TRUST_TENANT_HEADERS", flag)
    assert resolve_tenant_ids(SPOOFED_HEADERS) == (ENV_AGENT, ENV_ORG)


def test_resolve_tenant_ids_trusted_falls_back_to_env(kv_env, monkeypatch):
    monkeypatch.setenv("WRITER_TRUST_TENANT_HEADERS", "1")
    assert resolve_tenant_ids({}) == (ENV_AGENT, ENV_ORG)
    assert resolve_tenant_ids(None) == (ENV_AGENT, ENV_ORG)
    assert resolve_tenant_ids({"x-agent-id": "a"}) == ("a", ENV_ORG)


def test_vault_cache_is_keyed_by_tenant(kv_env, monkeypatch):
    monkeypatch.setenv("WRITER_TRUST_TENANT_HEADERS", "1")
    storage, seen = _recording_storage()
    monkeypatch.setattr(vault_module, "writer_kv_storage", storage)
    vault = WriterVault()

    _use_session_headers(monkeypatch, SPOOFED_HEADERS)
    assert vault.get_secrets() == {"tenant": "victim-agent"}

    _use_session_headers(monkeypatch, {"x-agent-id": "agent-b", "x-organization-id": "org-b"})
    assert vault.get_secrets() == {"tenant": "agent-b"}
    assert vault.get_secrets() == {"tenant": "agent-b"}
    assert len(seen) == 2

    _use_session_headers(monkeypatch, SPOOFED_HEADERS)
    assert vault.get_secrets() == {"tenant": "victim-agent"}
    assert len(seen) == 2


def test_vault_refresh_clears_all_tenants(kv_env, monkeypatch):
    storage, seen = _recording_storage()
    monkeypatch.setattr(vault_module, "writer_kv_storage", storage)
    vault = WriterVault()
    _use_session_headers(monkeypatch, None)

    vault.get_secrets()
    vault.get_secrets()
    assert len(seen) == 1

    vault.refresh()
    assert vault.get_secrets() == {"tenant": ENV_AGENT}
    assert len(seen) == 2


def test_vault_cache_evicts_least_recently_used_tenant(kv_env, monkeypatch):
    monkeypatch.setenv("WRITER_TRUST_TENANT_HEADERS", "1")
    monkeypatch.setattr(vault_module, "MAX_CACHED_TENANTS", 2)
    storage, seen = _recording_storage()
    monkeypatch.setattr(vault_module, "writer_kv_storage", storage)
    vault = WriterVault()

    def use(agent):
        _use_session_headers(monkeypatch, {"x-agent-id": agent, "x-organization-id": "org"})
        return vault.get_secrets()

    use("a")
    use("b")
    use("a")
    use("c")
    assert len(seen) == 3

    assert use("a") == {"tenant": "a"}
    assert len(seen) == 3
    assert use("b") == {"tenant": "b"}
    assert len(seen) == 4
