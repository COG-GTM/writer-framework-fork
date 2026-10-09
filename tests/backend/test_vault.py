import httpx
import pytest
from writer import vault as vault_module
from writer.keyvalue_storage import KeyValueStorage
from writer.vault import WriterVault

DEPLOYMENT_AGENT_ID = "deployment-agent"
DEPLOYMENT_ORG_ID = "deployment-org"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(vault_module.time, "monotonic", fake.monotonic)
    return fake


@pytest.fixture
def deployment_env(monkeypatch):
    monkeypatch.setenv("WRITER_BASE_URL", "https://writer.test")
    monkeypatch.setenv("WRITER_API_KEY", "server-key")
    monkeypatch.setenv("WRITER_APP_ID", DEPLOYMENT_AGENT_ID)
    monkeypatch.setenv("WRITER_ORG_ID", DEPLOYMENT_ORG_ID)


@pytest.fixture
def spoofed_session_ids(monkeypatch):
    monkeypatch.setattr(
        KeyValueStorage, "_get_agent_ids", lambda self: ("attacker-agent", "attacker-org")
    )


class VaultBackend:
    def __init__(self) -> None:
        self.requests = []
        self.responses = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0) if self.responses else httpx.Response(
            200, json={"secret": {"API_TOKEN": "s3cret"}}
        )
        if isinstance(response, Exception):
            raise response
        return response

    def make_vault(self) -> WriterVault:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        return WriterVault(kv_storage=KeyValueStorage(client=client))


@pytest.fixture
def backend(deployment_env, spoofed_session_ids):
    return VaultBackend()


def test_fetch_uses_deployment_identity_not_session_headers(backend, clock):
    vault = backend.make_vault()

    assert vault.get_secrets() == {"API_TOKEN": "s3cret"}

    request = backend.requests[0]
    assert request.url.path == "/v1/agent_secret/vault"
    assert request.headers["X-Agent-Id"] == DEPLOYMENT_AGENT_ID
    assert request.headers["X-Organization-Id"] == DEPLOYMENT_ORG_ID


def test_session_headers_still_used_for_regular_kv_access(backend):
    client = httpx.Client(transport=httpx.MockTransport(backend.handler))
    KeyValueStorage(client=client).get("some-key", "data")

    assert backend.requests[0].headers["X-Agent-Id"] == "attacker-agent"


def test_successful_fetch_is_cached(backend, clock):
    vault = backend.make_vault()

    vault.get_secrets()
    vault.get_secrets()

    assert len(backend.requests) == 1


def test_failed_fetch_is_not_cached_and_retried_after_backoff(backend, clock):
    backend.responses = [httpx.Response(403, json={"detail": "forbidden"})]
    vault = backend.make_vault()

    assert vault.get_secrets() == {}
    assert vault.secrets is None

    assert vault.get_secrets() == {}
    assert len(backend.requests) == 1

    clock.now += WriterVault.RETRY_BASE_SECONDS
    assert vault.get_secrets() == {"API_TOKEN": "s3cret"}
    assert len(backend.requests) == 2


def test_backoff_grows_exponentially_and_is_capped(backend, clock):
    backend.responses = [httpx.Response(500)] * 20
    vault = backend.make_vault()

    delays = []
    for _ in range(10):
        start = clock.now
        vault.get_secrets()
        delays.append(vault._next_retry_at - start)
        clock.now = vault._next_retry_at

    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    assert max(delays) == WriterVault.RETRY_MAX_SECONDS


def test_transport_errors_are_handled(backend, clock):
    backend.responses = [httpx.ConnectError("boom")]
    vault = backend.make_vault()

    assert vault.get_secrets() == {}
    assert vault.secrets is None


def test_invalid_response_format_is_not_cached(backend, clock):
    backend.responses = [httpx.Response(200, json={"secret": "not-a-dict"})]
    vault = backend.make_vault()

    assert vault.get_secrets() == {}
    assert vault.secrets is None


def test_missing_deployment_ids_does_not_fall_back_to_session_headers(backend, clock, monkeypatch):
    monkeypatch.delenv("WRITER_APP_ID")
    vault = backend.make_vault()

    assert vault.get_secrets() == {}
    assert backend.requests == []
    assert vault.secrets is None


def test_refresh_failure_keeps_previous_secrets(backend, clock):
    vault = backend.make_vault()
    vault.get_secrets()

    backend.responses = [httpx.Response(503)]
    vault.refresh()

    assert vault.get_secrets() == {"API_TOKEN": "s3cret"}


def test_returned_secrets_are_a_copy(backend, clock):
    vault = backend.make_vault()

    vault.get_secrets()["API_TOKEN"] = "tampered"

    assert vault.get_secrets() == {"API_TOKEN": "s3cret"}


def test_missing_vault_is_cached_as_empty(backend, clock):
    backend.responses = [httpx.Response(404, json={"detail": "not found"})]
    vault = backend.make_vault()

    assert vault.get_secrets() == {}
    assert vault.get_secrets() == {}

    assert vault.secrets == {}
    assert len(backend.requests) == 1
