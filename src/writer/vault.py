"""
Writer Vault module for managing secret retrieval and caching.

This module provides the WriterVault class which handles fetching and caching
secrets from the Writer vault service, with support for environment-based
configuration and error handling.
"""

import logging
from typing import Dict, Optional, Tuple

import httpx

from writer.keyvalue_storage import writer_kv_storage

logger = logging.getLogger("vault")


class WriterVault:
    """Manages retrieval and caching of secrets from the Writer vault service."""

    def __init__(self) -> None:
        """Initialize vault with an empty per-tenant cache."""
        self._secrets: Dict[Tuple[Optional[str], Optional[str]], Dict] = {}

    def get_secrets(self) -> Dict:
        """Get cached secrets for the current agent/org, fetching from vault if not already loaded."""
        tenant = writer_kv_storage.get_agent_ids()
        secrets = self._secrets.get(tenant)
        if secrets is None:
            secrets = self._fetch()
            self._secrets[tenant] = secrets
        return secrets

    def refresh(self):
        """Drop cached secrets for every agent/org so the next access refetches them."""
        self._secrets = {}

    def _fetch(self) -> Dict:
        try:
            data = writer_kv_storage.get("vault", "secret")
            secrets = data.get("secret")
            if isinstance(secrets, dict):
                return secrets
            logger.warning("Invalid vault response format: expected dict in 'secret' field")
        except (httpx.HTTPStatusError, ValueError) as e:
            logger.error("Failed to fetch vault secrets: %s", e)
        return {}


writer_vault = WriterVault()
