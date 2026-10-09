"""
Outbound request policy for blocks that call user-configured URLs.

By default, requests may only target public http(s) destinations. The
following environment variables relax or tighten the policy:

- ``WRITER_HTTP_REQUEST_ALLOWED_HOSTS``: comma-separated host allowlist.
  Entries may use a leading wildcard (``*.example.com``). When set, any other
  host is rejected.
- ``WRITER_HTTP_REQUEST_ALLOW_PRIVATE_NETWORKS``: set to ``true`` to allow
  loopback, private, link-local and other non-public addresses. Cloud
  metadata endpoints stay blocked.
"""

import ipaddress
import os
import socket
from typing import Iterable, List, Optional, Union

import httpcore
import httpx

from writer.ss_types import WriterConfigurationError

ALLOWED_HOSTS_ENV = "WRITER_HTTP_REQUEST_ALLOWED_HOSTS"
ALLOW_PRIVATE_NETWORKS_ENV = "WRITER_HTTP_REQUEST_ALLOW_PRIVATE_NETWORKS"
ALLOWED_SCHEMES = ("http", "https")

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in (
        "169.254.169.254",  # AWS, GCP, Azure, OpenStack
        "169.254.170.2",  # AWS ECS task metadata
        "169.254.169.123",  # AWS time sync
        "100.100.100.200",  # Alibaba Cloud
        "fd00:ec2::254",  # AWS IPv6
    )
)


class EgressPolicyError(WriterConfigurationError):
    pass


def _allowed_hosts() -> List[str]:
    raw = os.getenv(ALLOWED_HOSTS_ENV, "")
    return [h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip()]


def _private_networks_allowed() -> bool:
    return os.getenv(ALLOW_PRIVATE_NETWORKS_ENV, "").strip().lower() in ("1", "true", "yes")


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return host == pattern


def _normalise_ip(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_ip_allowed(ip: IPAddress) -> bool:
    ip = _normalise_ip(ip)
    if ip in METADATA_ADDRESSES:
        return False
    if _private_networks_allowed():
        return True
    return ip.is_global and not ip.is_multicast


def resolve_host(host: str, port: int) -> List[IPAddress]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]


def _blocked(host: str) -> EgressPolicyError:
    return EgressPolicyError(
        f"The HTTP request to host `{host}` was blocked by the outbound request policy."
    )


def check_url(url: Union[str, httpx.URL]) -> None:
    """
    Rejects URLs whose scheme, host or resolved addresses aren't allowed.
    Hosts that can't be resolved are left to fail at connection time, where
    the connected peer address is checked again.
    """
    try:
        parsed = httpx.URL(url) if isinstance(url, str) else url
    except httpx.InvalidURL as e:
        raise EgressPolicyError("The HTTP request URL is invalid.") from e

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise EgressPolicyError("Only http and https URLs are allowed in HTTP requests.")

    host = parsed.host.lower().rstrip(".")
    if not host:
        raise EgressPolicyError("The HTTP request URL doesn't specify a host.")

    allowed_hosts = _allowed_hosts()
    if allowed_hosts and not any(_host_matches(host, p) for p in allowed_hosts):
        raise _blocked(host)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = resolve_host(host, port)
    except (socket.gaierror, UnicodeError, ValueError):
        return
    if not addresses or not all(is_ip_allowed(ip) for ip in addresses):
        raise _blocked(host)


def request_hook(request: httpx.Request) -> None:
    check_url(request.url)


class _GuardedNetworkBackend(httpcore.NetworkBackend):
    """
    Verifies the address actually connected to, which protects against DNS
    answers changing between the policy check and the connection.
    """

    def __init__(self, backend: httpcore.NetworkBackend):
        self._backend = backend

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Iterable] = None,
    ) -> httpcore.NetworkStream:
        stream = self._backend.connect_tcp(
            host, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )
        sock = stream.get_extra_info("socket")
        try:
            peer = ipaddress.ip_address(sock.getpeername()[0].split("%")[0])
        except Exception:
            peer = None
        if peer is None or not is_ip_allowed(peer):
            stream.close()
            raise _blocked(host)
        return stream

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise EgressPolicyError("Unix socket connections are not allowed in HTTP requests.")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class GuardedHTTPTransport(httpx.HTTPTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pool = getattr(self, "_pool", None)
        if isinstance(pool, httpcore.ConnectionPool) and not isinstance(
            pool, (httpcore.HTTPProxy, httpcore.SOCKSProxy)
        ):
            pool._network_backend = _GuardedNetworkBackend(pool._network_backend)
