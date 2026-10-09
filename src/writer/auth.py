import asyncio
import base64
import binascii
import dataclasses
import hmac
import ipaddress
import logging
import os.path
import threading
import time
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from typing import Callable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

from authlib.integrations.requests_client.oauth2_session import OAuth2Session  # type: ignore
from fastapi import Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import writer.serve
from writer.core import session_manager
from writer.serve import WriterFastAPI
from writer.ss_types import InitSessionRequestPayload

logger = logging.getLogger('writer')

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


class FailedAttempts:
    """
    Bounded, expiring counter of failed logins per key (client IP or username).

    A key is throttled once it reaches `limit` failures within `window` seconds and stays
    throttled until that window ends. Expired keys are dropped and the oldest keys are
    evicted beyond `max_entries`, so memory stays bounded.

    >>> attempts = FailedAttempts(window=5, limit=1, max_entries=1000)
    >>> attempts.record("1.2.3.4")
    >>> attempts.retry_after("1.2.3.4")
    """

    def __init__(self, window: float, limit: int = 1, max_entries: int = 10000):
        self.window = window
        self.limit = limit
        self.max_entries = max_entries
        self._entries: "OrderedDict[str, Tuple[float, int]]" = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def record(self, key: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._prune(now)
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = (now, 1)
            else:
                self._entries[key] = (entry[0], entry[1] + 1)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def retry_after(self, key: str, now: Optional[float] = None) -> float:
        """
        Seconds the key still has to wait before its next attempt (0 if it may try now).
        """
        now = time.time() if now is None else now
        with self._lock:
            self._prune(now)
            entry = self._entries.get(key)
            if entry is None or entry[1] < self.limit:
                return 0
            return max(0.0, self.window - (now - entry[0]))

    def _prune(self, now: float) -> None:
        # Entries are kept in window-start order, so expired ones are always at the front.
        while self._entries:
            window_start, _ = next(iter(self._entries.values()))
            if now - window_start < self.window:
                break
            self._entries.popitem(last=False)


class Unauthorized(Exception):
    """
    This exception allows you to reject the authentication of a user.

    >>>
    """
    def __init__(self, status_code = 401, message = "Unauthorized", more_info = ""):
        self.status_code = status_code
        self.message = message
        self.more_info = more_info


class Auth:
    """
    Interface to implement authentication in Writer Framework.
    """
    __metaclass__ = ABCMeta

    @abstractmethod
    def register(self,
                 asgi_app: WriterFastAPI,
                 callback: Optional[Callable[[Request, str, dict], None]] = None,
                 unauthorized_action: Optional[Callable[[Request, Unauthorized], Response]] = None
    ):
        raise NotImplementedError

@dataclasses.dataclass
class BasicAuth(Auth):
    """
    Configure Writer Framework to use Basic Authentication. If this is set, Writer Framework will
    ask anonymous users to authenticate using Basic Authentication.

    >>> _auth = auth.BasicAuth(
    >>>     login=os.getenv('LOGIN'),
    >>>     password=os.getenv('PASSWORD')
    >>> )
    >>> writer.server.register_auth(_auth)

    Brute force protection
    ----------------------

    A simple brute force protection is implemented by default. If a login fails, the client IP has to wait
    `delay_after_failure` seconds (1 second by default) before it can try again. Independently of the IP, a username
    is rejected for the rest of a `username_failure_window` (60 seconds by default) once it has collected
    `max_failures_per_username` failed logins (10 by default) in that window. Set `max_failures_per_username=None`
    to disable the per-username limit.

    The client IP is the address of the TCP peer (`request.client.host`). When uvicorn runs with `--proxy-headers`
    (the default), it already rewrites the peer from `X-Forwarded-For` for the proxies listed in `--forwarded-allow-ips`.
    `X-Forwarded-For` / `X-Real-IP` are only read by Writer Framework when the peer is listed in `trusted_proxies`
    (IP addresses or CIDR ranges); otherwise they are ignored, because any client can set them.

    >>> _auth = auth.BasicAuth(
    >>>     login=os.getenv('LOGIN'),
    >>>     password=os.getenv('PASSWORD'),
    >>>     trusted_proxies=["10.0.0.0/8"]
    >>> )

    Failures are kept in memory only for their window, for at most `max_tracked_failures` IPs and as many usernames.

    >>> _auth = auth.BasicAuth(
    >>>     login=os.getenv('LOGIN'),
    >>>     password=os.getenv('PASSWORD')
    >>>     delay_after_failure=5 # 5 seconds delay after a failed login
    >>> )
    >>> writer.server.register_auth(_auth)

    The user is stuck by default after a failure.

    >>> _auth = auth.BasicAuth(
    >>>     login=os.getenv('LOGIN'),
    >>>     password=os.getenv('PASSWORD'),
    >>>     delay_after_failure=5,
    >>>     block_user_after_failure=False
    >>> )
    """
    login: str
    password: str
    delay_after_failure: int = 1  # limit attempt when authentication fail (reduce brute force risk)
    block_user_after_failure: bool = True  # delay the answer to the user after a failed login
    trusted_proxies: Sequence[str] = ()  # proxies (IP or CIDR) allowed to set X-Forwarded-For / X-Real-IP
    max_failures_per_username: Optional[int] = 10  # failed logins per username allowed within username_failure_window
    username_failure_window: int = 60
    max_tracked_failures: int = 10000  # upper bound of client IPs (and of usernames) remembered after a failure

    failed_attempts: Optional[FailedAttempts] = dataclasses.field(default=None, init=False, repr=False)
    failed_attempts_per_username: Optional[FailedAttempts] = dataclasses.field(default=None, init=False, repr=False)

    callback_func: Optional[Callable[[Request, str, dict], None]] = None  # Callback to validate user authentication
    unauthorized_action: Optional[Callable[[Request, Unauthorized], Response]] = None  # Callback to build its own page when a user is not allowed


    def register(self,
                 asgi_app: WriterFastAPI,
                 callback: Optional[Callable[[Request, str, dict], None]] = None,
                 unauthorized_action: Optional[Callable[[Request, Unauthorized], Response]] = None):

        self.unauthorized_action = unauthorized_action
        self.callback_func = callback

        failed_attempts = FailedAttempts(window=self.delay_after_failure, limit=1, max_entries=self.max_tracked_failures)
        failed_attempts_per_username = FailedAttempts(
            window=self.username_failure_window,
            limit=self.max_failures_per_username or 0,
            max_entries=self.max_tracked_failures,
        )
        self.failed_attempts = failed_attempts
        self.failed_attempts_per_username = failed_attempts_per_username
        trusted_networks = _parse_networks(self.trusted_proxies)

        @asgi_app.middleware("http")
        async def basicauth_middleware(request: Request, call_next):
            client_ip = _client_ip(request, trusted_networks)
            username: Optional[str] = None

            try:
                remaining_time = failed_attempts.retry_after(client_ip)
                if remaining_time > 0:
                    raise Unauthorized(status_code=429, message="Too Many Requests", more_info=f"You can try to log in every {self.delay_after_failure}s. Your next try is in {int(remaining_time)}s.")

                session_id = session_manager.generate_session_id()
                _auth = request.headers.get('Authorization')
                if _auth is None:
                    return HTMLResponse("", status.HTTP_401_UNAUTHORIZED, {"WWW-Authenticate": "Basic"})

                scheme, _, data = _auth.partition(' ')
                if scheme != 'Basic':
                    return HTMLResponse("", status.HTTP_401_UNAUTHORIZED, {"WWW-Authenticate": "Basic"})

                try:
                    username, password = base64.b64decode(data, validate=True).decode().split(':', 1)
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    raise Unauthorized()

                if self.max_failures_per_username:
                    remaining_time = failed_attempts_per_username.retry_after(username)
                    if remaining_time > 0:
                        raise Unauthorized(status_code=429, message="Too Many Requests", more_info=f"Too many failed logins for this user. Your next try is in {int(remaining_time)}s.")

                if self.callback_func:
                    self.callback_func(request, session_id, {'username': username})
                else:
                    login_ok = hmac.compare_digest(username.encode(), self.login.encode())
                    password_ok = hmac.compare_digest(password.encode(), self.password.encode())
                    if not (login_ok and password_ok):
                        raise Unauthorized()

                return await call_next(request)
            except Unauthorized as exc:
                if exc.status_code != 429:
                    failed_attempts.record(client_ip)
                    if username is not None and self.max_failures_per_username:
                        failed_attempts_per_username.record(username)

                    if self.block_user_after_failure:
                        await asyncio.sleep(self.delay_after_failure)

                if self.unauthorized_action is not None:
                    return self.unauthorized_action(request, exc)
                else:
                    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
                    return templates.TemplateResponse(request=request, name="auth_unauthorized.html", status_code=exc.status_code, context={
                        "status_code": exc.status_code,
                        "message": exc.message,
                        "more_info": exc.more_info
                    })

@dataclasses.dataclass
class Oidc(Auth):
    """
    Configure Writer Framework to use OpenID Connect. If this is set, Writer Framework will
    redirect anonymous users to OpenID Connect issuer.

    The issuer will then
    authenticate the user and redirect back to the Writer Framework application with
    an authorization code. The Writer Framework application will then exchange the
    authorization code for an access token and use the access token to
    authenticate the user and fetch user information.

    >>> oidc = Oidc(
    ...     client_id="xxxxxxx",
    ...     client_secret="xxxxxxxxxxxxx.apps.googleusercontent.com",
    ...     url_authorize="https://accounts.google.com/o/oauth2/auth",
    ...     url_oauthtoken="https://oauth2.googleapis.com/token",
    ...     url_userinfo="https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
    ... )
    >>> writer.server.register_auth(oidc)

    """
    client_id: str
    client_secret: str
    host_url: str
    url_authorize: str
    url_oauthtoken: str
    scope: str = "openid email profile"
    callback_authorize: str = "authorize"
    url_userinfo: Optional[str] = None
    app_static_public: bool = False

    authlib: OAuth2Session = None
    callback_func: Optional[Callable[[Request, str, dict], None]] = None # Callback to validate user authentication
    unauthorized_action: Optional[Callable[[Request, Unauthorized], Response]] = None # Callback to build its own page when a user is not allowed


    def register(self,
                 asgi_app: WriterFastAPI,
                 callback: Optional[Callable[[Request, str, dict], None]] = None,
                 unauthorized_action: Optional[Callable[[Request, Unauthorized], Response]] = None
                 ):

        redirect_url = urljoin(self.host_url, self.callback_authorize)
        host_url_path = urlpath(self.host_url)
        callback_authorize_path = urljoin(host_url_path, self.callback_authorize)

        auth_authorized_prefix_paths = []
        auth_authorized_routes = [callback_authorize_path]

        for asset_path in writer.serve.wf_root_static_assets():
            if asset_path.is_file():
                auth_authorized_routes.append(urljoin(host_url_path, asset_path.name))
            elif asset_path.is_dir():
                auth_authorized_prefix_paths.append(urljoin(host_url_path, asset_path.name))

        if self.app_static_public is True:
            auth_authorized_prefix_paths += [urljoin(host_url_path, "static"), urljoin(host_url_path, "extensions")]

        logger.debug(f"[auth] oidc - url redirect: {redirect_url}")
        logger.debug(f"[auth] oidc - endpoint authorize: {self.url_authorize}")
        logger.debug(f"[auth] oidc - endpoint token: {self.url_oauthtoken}")
        logger.debug(f"[auth] oidc - path: {host_url_path}")
        logger.debug(f"[auth] oidc - auth authorized routes: {auth_authorized_routes}")
        logger.debug(f"[auth] oidc - auth authorized prefix paths: {auth_authorized_prefix_paths}")
        self.authlib = OAuth2Session(
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope=self.scope.split(" "),
            redirect_uri=redirect_url,
            authorization_endpoint=self.url_authorize,
            token_endpoint=self.url_oauthtoken,
        )

        self.unauthorized_action = unauthorized_action
        self.callback_func = callback

        @asgi_app.middleware("http")
        async def oidc_middleware(request: Request, call_next):
            session = request.cookies.get('session')

            is_one_of_url_prefix_allowed = any(request.url.path.startswith(url_prefix) for url_prefix in auth_authorized_prefix_paths)
            if session is not None or request.url.path in auth_authorized_routes or is_one_of_url_prefix_allowed:
                response: Response = await call_next(request)
                return response
            else:
                url = self.authlib.create_authorization_url(self.url_authorize)
                response = RedirectResponse(url=url[0])
                return response

        @asgi_app.get('/' + urlstrip(self.callback_authorize))
        async def route_callback(request: Request):
            self.authlib.fetch_token(url=self.url_oauthtoken, authorization_response=str(request.url))
            try:
                host_url_path = urlpath(self.host_url)
                response = RedirectResponse(url=host_url_path)
                session_id = session_manager.generate_session_id()

                app_runner = writer.serve.app_runner(asgi_app)
                await app_runner.init_session(InitSessionRequestPayload(
                    cookies=request.cookies, headers=request.headers, proposedSessionId=session_id))

                userinfo = {}
                if self.url_userinfo:
                    userinfo = self.authlib.get(self.url_userinfo).json()

                if self.callback_func:
                    self.callback_func(request, session_id, userinfo)

                if self.url_userinfo:
                    app_runner.set_userinfo(session_id=session_id, userinfo=userinfo)

                response.set_cookie(key="session", value=session_id, httponly=True)
                return response
            except Unauthorized as exc:
                if self.unauthorized_action is not None:
                    return self.unauthorized_action(request, exc)
                else:
                    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
                    return templates.TemplateResponse(request=request, name="auth_unauthorized.html", status_code=exc.status_code, context={
                        "status_code": exc.status_code,
                        "message": exc.message,
                        "more_info": exc.more_info
                    })


def Google(client_id: str, client_secret: str, host_url: str, app_static_public = False) -> Oidc:
    """
    Configure Google Social login configured through Client Id for Web application in Google Cloud Console.

    >>> import writer.auth
    >>> oidc = writer.auth.Google(client_id="xxxxxxx", client_secret="xxxxxxxxxxxxx.apps.googleusercontent.com", host_url="http://localhost:5000")

    :param client_id: client id of Web application
    :param client_secret: client secret of Web application
    :param host_url: The URL of the Writer Framework application (for callback)
    :param app_static_public: authorizes the exposure of the user's static assets (/static and /extensions)
    """
    return Oidc(
        client_id=client_id,
        client_secret=client_secret,
        host_url=host_url,
        url_authorize="https://accounts.google.com/o/oauth2/auth",
        url_oauthtoken="https://oauth2.googleapis.com/token",
        url_userinfo="https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
        app_static_public=app_static_public
    )

def Github(client_id: str, client_secret: str, host_url: str, app_static_public = False) -> Oidc:
    """
    Configure Github authentication.

    >>> import writer.auth
    >>> oidc = writer.auth.Github(client_id="xxxxxxx", client_secret="xxxxxxxxxxxxx", host_url="http://localhost:5000")

    :param client_id: client id
    :param client_secret: client secret
    :param host_url: The URL of the Writer Framework application (for callback)
    :param app_static_public: authorizes the exposure of the user's static assets (/static and /extensions)
    """

    return Oidc(
        client_id=client_id,
        client_secret=client_secret,
        host_url=host_url,
        url_authorize="https://github.com/login/oauth/authorize",
        url_oauthtoken="https://github.com/login/oauth/access_token",
        url_userinfo="https://api.github.com/user",
        app_static_public=app_static_public
    )

def Auth0(client_id: str, client_secret: str, domain: str, host_url: str, app_static_public = False) -> Oidc:
    """
    Configure Auth0 application for authentication.

    >>> import writer.auth
    >>> oidc = writer.auth.Auth0(client_id="xxxxxxx", client_secret="xxxxxxxxxxxxx", domain="xxx-xxxxx.eu.auth0.com", host_url="http://localhost:5000")

    :param client_id: client id
    :param client_secret: client secret
    :param domain: Domain of the Auth0 application
    :param host_url: The URL of the Writer Framework application (for callback)
    :param app_static_public: authorizes the exposure of the user's static assets (/static and /extensions)
    """

    return Oidc(
        client_id=client_id,
        client_secret=client_secret,
        host_url=host_url,
        url_authorize=f"https://{domain}/authorize",
        url_oauthtoken=f"https://{domain}/oauth/token",
        url_userinfo=f"https://{domain}/userinfo",
        app_static_public=app_static_public
    )

def urlpath(url: str):
    """
    >>> urlpath("http://localhost/app1")
    >>> "/app1"

    >>> urlpath("http://localhost")
    >>> "/"
    """
    path = urlparse(url).path
    if len(path) == 0:
        return "/"
    else:
        return path

def urljoin(*args):
    """
    >>> urljoin("http://localhost/app1", "edit")
    >>> "http://localhost/app1/edit"

    >>> urljoin("app1/", "edit")
    >>> "app1/edit"

    >>> urljoin("app1", "edit")
    >>> "app1/edit"

    >>> urljoin("/app1/", "/edit")
    >>> "/app1/edit"
    """
    root_part = args[0]
    root_part_is_root_path = root_part.startswith('/') and len(root_part) > 1

    url_strip_parts = []
    for part in args:
        if part:
            url_strip_parts.append(urlstrip(part))

    return '/'.join(url_strip_parts) if root_part_is_root_path is False else '/' + '/'.join(url_strip_parts)

def urlstrip(url_path: str):
    """

    >>> urlstrip("/app1/")
    >>> "app1"

    >>> urlstrip("http://localhost/app1")
    >>> "http://localhost/app1"

    >>> urlstrip("http://localhost/app1/")
    >>> "http://localhost/app1"
    """
    return url_path.strip('/')

def _parse_networks(addresses: Sequence[str]) -> List[IPNetwork]:
    """
    >>> _parse_networks(["10.0.0.0/8", "127.0.0.1"])
    """
    return [ipaddress.ip_network(address.strip(), strict=False) for address in addresses]


def _is_trusted(address: str, trusted_networks: Sequence[IPNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in network for network in trusted_networks)


def _client_ip(request: Request, trusted_networks: Sequence[IPNetwork] = ()) -> str:
    """
    Get the client IP address from the request.

    The TCP peer address is used unless the peer is a trusted proxy. Only then are
    `X-Forwarded-For` (read right to left, skipping trusted proxies) and `X-Real-IP` used.

    >>> _client_ip(request)
    >>> _client_ip(request, _parse_networks(["10.0.0.0/8"]))
    """
    client = request.client
    peer_ip = client.host if client is not None else ""
    if not _is_trusted(peer_ip, trusted_networks):
        return peer_ip

    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        hops = [hop.strip() for hop in x_forwarded_for.split(",") if hop.strip()]
        for hop in reversed(hops):
            if not _is_trusted(hop, trusted_networks):
                return hop
        if hops:
            return hops[0]

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    return peer_ip
