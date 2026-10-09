import http.server
import ipaddress
import socket
import threading

import httpx
import pytest

from writer.blocks import egress
from writer.blocks.httprequest import HTTPRequest

PUBLIC_IP = "93.184.215.14"


def fake_resolver(mapping):
    def resolve(host, port):
        if host in mapping:
            return [ipaddress.ip_address(ip) for ip in mapping[host]]
        try:
            return [ipaddress.ip_address(host.strip("[]"))]
        except ValueError:
            raise socket.gaierror("not found")

    return resolve


@pytest.fixture(autouse=True)
def clean_policy_env(monkeypatch):
    monkeypatch.delenv(egress.ALLOWED_HOSTS_ENV, raising=False)
    monkeypatch.delenv(egress.ALLOW_PRIVATE_NETWORKS_ENV, raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://172.16.1.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00:ec2::254]/",
        "http://[fe80::1]/",
        "http://224.0.0.1/",
    ],
)
def test_non_public_addresses_are_blocked(url):
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url(url)


def test_localhost_name_is_blocked():
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("http://localhost:3000/")


def test_hostname_resolving_to_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(
        egress, "resolve_host", fake_resolver({"internal.example.com": ["10.1.2.3"]})
    )
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("https://internal.example.com/")


def test_hostname_with_any_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(
        egress, "resolve_host", fake_resolver({"mixed.example.com": [PUBLIC_IP, "127.0.0.1"]})
    )
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("https://mixed.example.com/")


def test_public_destination_is_allowed(monkeypatch):
    monkeypatch.setattr(egress, "resolve_host", fake_resolver({"api.example.com": [PUBLIC_IP]}))
    egress.check_url("https://api.example.com/v1/items?x=1")
    egress.check_url(f"http://{PUBLIC_IP}/")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/", "gopher://127.0.0.1:6379/", "example.com"]
)
def test_non_http_schemes_are_blocked(url):
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url(url)


def test_unresolvable_host_is_left_to_the_connection(monkeypatch):
    monkeypatch.setattr(egress, "resolve_host", fake_resolver({}))
    egress.check_url("https://does-not-resolve.example.com/")


def test_allowlist_restricts_hosts(monkeypatch):
    monkeypatch.setattr(
        egress,
        "resolve_host",
        fake_resolver(
            {"api.example.com": [PUBLIC_IP], "a.b.trusted.io": [PUBLIC_IP], "evil.com": [PUBLIC_IP]}
        ),
    )
    monkeypatch.setenv(egress.ALLOWED_HOSTS_ENV, "api.example.com, *.trusted.io")
    egress.check_url("https://api.example.com/")
    egress.check_url("https://a.b.trusted.io/")
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("https://evil.com/")
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("https://trusted.io.evil.com/")


def test_allowlist_does_not_open_private_addresses(monkeypatch):
    monkeypatch.setattr(egress, "resolve_host", fake_resolver({"intranet": ["10.0.0.2"]}))
    monkeypatch.setenv(egress.ALLOWED_HOSTS_ENV, "intranet")
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("http://intranet/")


def test_private_networks_opt_in_keeps_metadata_blocked(monkeypatch):
    monkeypatch.setenv(egress.ALLOW_PRIVATE_NETWORKS_ENV, "true")
    egress.check_url("http://10.0.0.5/")
    egress.check_url("http://127.0.0.1:8080/")
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(egress.EgressPolicyError):
        egress.check_url("http://[::ffff:169.254.169.254]/")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        body = b"internal secret"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_connected_peer_is_checked_after_dns_resolution(session, runner, monkeypatch, local_server):
    # Simulates DNS rebinding: the policy check sees a public address but the
    # connection lands on loopback.
    monkeypatch.setattr(egress, "resolve_host", fake_resolver({"127.0.0.1": [PUBLIC_IP]}))
    component = session.add_fake_component({"url": f"http://127.0.0.1:{local_server}/"})
    block = HTTPRequest(component, runner, {})
    with pytest.raises(egress.EgressPolicyError):
        block.run()
    assert block.outcome == "connectionError"
    assert block.result is None


def test_private_destination_reachable_when_opted_in(session, runner, monkeypatch, local_server):
    monkeypatch.setenv(egress.ALLOW_PRIVATE_NETWORKS_ENV, "true")
    component = session.add_fake_component({"url": f"http://127.0.0.1:{local_server}/"})
    block = HTTPRequest(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert block.result["body"] == "internal secret"


def test_redirects_are_checked(session, runner, monkeypatch, local_server):
    monkeypatch.setenv(egress.ALLOW_PRIVATE_NETWORKS_ENV, "true")
    component = session.add_fake_component({})
    block = HTTPRequest(component, runner, {})
    with block.acquire_httpx_client() as client:
        with pytest.raises(egress.EgressPolicyError):
            client.get(f"http://127.0.0.1:{local_server}/redirect", follow_redirects=True)


def test_custom_client_redirects_are_checked(session, runner):
    def handler(request):
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="metadata")

    custom_client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    class CustomClientRequest(HTTPRequest, custom_httpx_client=custom_client):
        pass

    component = session.add_fake_component({"url": "http://93.184.216.34/", "method": "GET"})
    block = CustomClientRequest(component, runner, {})
    with pytest.raises(egress.EgressPolicyError):
        block.run()


def test_metadata_endpoint_blocked_by_block(session, runner):
    component = session.add_fake_component({"url": "http://169.254.169.254/latest/meta-data/"})
    block = HTTPRequest(component, runner, {})
    with pytest.raises(egress.EgressPolicyError):
        block.run()
    assert block.outcome == "connectionError"


def test_templated_host_cannot_reach_internal_address(session, runner):
    component = session.add_fake_component({"url": "@{payload}"})
    block = HTTPRequest(component, runner, {"payload": "http://127.0.0.1:22/"})
    with pytest.raises(egress.EgressPolicyError):
        block.run()
    assert block.outcome == "connectionError"


def test_guarded_transport_rejects_unix_sockets():
    with pytest.raises(egress.EgressPolicyError):
        egress._GuardedNetworkBackend(None).connect_unix_socket("/var/run/docker.sock")
