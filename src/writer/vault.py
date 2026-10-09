"""
Writer Vault module for managing secret retrieval and caching.

This module provides the WriterVault class which handles fetching and caching
secrets from the Writer vault service, with support for environment-based
configuration and error handling.

Secrets are always fetched with the deployment's own identity
(``WRITER_APP_ID`` / ``WRITER_ORG_ID``), never with ids taken from the
requesting session's headers, because the cache is shared by every session
in the process.
"""

import logging
import threading
import time
from typing import Dict, Optional

import httpx

from writer.keyvalue_storage import KeyValueStorage, writer_kv_storage

logger = logging.getLogger("vault")


class WriterVault:
    """Manages retrieval and caching of secrets from the Writer vault service."""

    RETRY_BASE_SECONDS = 1.0
    RETRY_MAX_SECONDS = 60.0

    def __init__(self, kv_storage: Optional[KeyValueStorage] = None) -> None:
        """Initialize vault with empty cache."""
        self._kv_storage = kv_storage
        self.secrets: Optional[Dict] = None
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._next_retry_at = 0.0

    def get_secrets(self) -> Dict:
        """
        Get cached secrets, fetching from vault if not already loaded.

        Failed fetches are not cached: an empty dict is returned and the fetch
        is retried on a later call, with exponential backoff.
        """
        with self._lock:
            if self.secrets is None and time.monotonic() >= self._next_retry_at:
                self._load()
            return dict(self.secrets) if self.secrets is not None else {}

    def refresh(self):
        """Force refresh of secrets from the vault service, keeping the previous cache on failure."""
        with self._lock:
            self._load()

    def _load(self) -> None:
        secrets = self._fetch()
        if secrets is None:
            self._consecutive_failures += 1
            delay = min(
                self.RETRY_BASE_SECONDS * (2 ** (self._consecutive_failures - 1)),
                self.RETRY_MAX_SECONDS,
            )
            self._next_retry_at = time.monotonic() + delay
            return
        self.secrets = secrets
        self._consecutive_failures = 0
        self._next_retry_at = 0.0

    def _fetch(self) -> Optional[Dict]:
        kv_storage = self._kv_storage or writer_kv_storage
        try:
            data = kv_storage.get(
                "vault", "secret", agent_ids=KeyValueStorage.deployment_agent_ids()
            )
            secrets = data.get("secret")
            if isinstance(secrets, dict):
                return secrets
            logger.warning("Invalid vault response format: expected dict in 'secret' field")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info("No vault secrets configured for this agent")
                return {}
            logger.error("Failed to fetch vault secrets: %s", e)
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Failed to fetch vault secrets: %s", e)
        return None


writer_vault = WriterVault()
