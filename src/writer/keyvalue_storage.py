import logging
import os
from functools import partial
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Tuple

import httpx

logger = logging.getLogger("kv_storage")

TRUST_TENANT_HEADERS_ENV = "WRITER_TRUST_TENANT_HEADERS"


def trust_tenant_headers() -> bool:
    """
    Tenant headers (x-agent-id / x-organization-id) are client-controlled
    unless a trusted proxy sets or strips them, so they are only honoured
    when the deployment explicitly opts in.
    """
    return os.getenv(TRUST_TENANT_HEADERS_ENV, "").strip().lower() in ("1", "true", "yes")


def resolve_tenant_ids(headers: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """Returns (agent_id, org_id) for the given session headers."""
    env_agent_id = os.getenv("WRITER_APP_ID")
    env_org_id = os.getenv("WRITER_ORG_ID")
    if not headers or not trust_tenant_headers():
        return (env_agent_id, env_org_id)
    agent_id = headers.get("x-agent-id") or env_agent_id
    org_id = headers.get("x-organization-id") or env_org_id
    return (agent_id, org_id)


class _WrappedRequestFunc(Protocol):
    def __call__(
        self,
        headers: Dict[str, str],
        timeout: int,
    ) -> httpx.Response: ...


class KeyValueStorage:
    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        base_url = os.getenv("WRITER_BASE_URL")
        self.api_key = os.getenv("WRITER_API_KEY")
        if None in (base_url, self.api_key):
            logger.warning("Missing required environment variables for KV storage access")
        self.api_url = f"{base_url}/v1" if base_url else None

        self._client = client if client is not None else httpx

    def get_agent_ids(self) -> Tuple[Optional[str], Optional[str]]:
        from writer.core import get_session
        current_session = get_session()
        headers = current_session.headers if current_session else None
        return resolve_tenant_ids(headers)

    def get(self, key: str, type_: Literal["data", "secret"]) -> Dict[str, Any]:
        return self._request(partial(self._client.get, url=f"{self.api_url}/agent_{type_}/{key}")).json()

    def get_data_keys(self) -> List[str]:
        return self._request(partial(self._client.get, url=f"{self.api_url}/agent_data")).json()["keys"]
    
    def save(self, key: str, data: Any) -> Dict[str, Any]:
        try:
            return self._create(key, data).json()
        except httpx.HTTPStatusError as e:
            if "already exists" in e.response.text:
                return self._update(key, data).json()
            raise e

    def _create(self, key: str, data: Any) -> httpx.Response:
        return self._request(partial(self._client.post, url=f"{self.api_url}/agent_data", json={"key": key, "data": data}))

    def _update(self, key: str, data: Any) -> httpx.Response:
        return self._request(partial(self._client.put, url=f"{self.api_url}/agent_data/{key}", json={"data": data}))

    def delete(self, key: str) -> Dict[str, str]:
        self._request(partial(self._client.delete, url=f"{self.api_url}/agent_data/{key}"))
        return {"key": key}

    def _request(self, request_func: _WrappedRequestFunc) -> httpx.Response:

        agent_id, org_id = self.get_agent_ids()
        if agent_id is None or org_id is None:
            raise ValueError("Can't access KV storage. Missing agent id or org id")

        if None in (self.api_key, self.api_url):
            raise ValueError("Can't access KV storage. Missing required env vars")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Organization-Id": org_id,
            "X-Agent-Id": agent_id,
        }

        response = request_func(headers=headers, timeout=3)
        response.raise_for_status()
        return response

    def is_accessible(self) -> bool:
        if None in self.get_agent_ids():
            return False
        if None in (self.api_key, self.api_url):
            return False
        return True

writer_kv_storage = KeyValueStorage()
