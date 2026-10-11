"""Who may open the service, and the headers every response carries."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import Request
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}
# Tailscale and other carrier-grade NAT addresses are private to the tunnel, but Python
# does not count 100.64.0.0/10 as private.
_SHARED_RANGE = ipaddress.ip_network("100.64.0.0/10")
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def host_allowed(header: str, allow_lan: bool, public_hosts: frozenset[str] = frozenset()) -> bool:
    """Accept this machine, a private IP on a trusted network, or a named public host.

    Unknown names are never accepted, so a web page cannot point its own domain at this
    service (DNS rebinding).
    """
    name = _host_name(header)
    if name in _LOCAL_NAMES:
        return True
    if name in public_hosts:
        return True
    if not allow_lan:
        return False
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address in _SHARED_RANGE
    )


def _host_name(header: str) -> str:
    value = header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class AllowedHosts:
    def __init__(
        self, app: ASGIApp, allow_lan: bool, public_hosts: frozenset[str] = frozenset()
    ) -> None:
        self.app = app
        self.allow_lan = allow_lan
        self.public_hosts = public_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            if not host_allowed(
                Headers(scope=scope).get("host", ""), self.allow_lan, self.public_hosts
            ):
                if scope["type"] == "http":
                    await PlainTextResponse("Invalid host header", status_code=400)(
                        scope, receive, send
                    )
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def same_origin(request: Request) -> bool:
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if origin:
        return urlsplit(origin).netloc == host
    referer = request.headers.get("referer")
    if referer:
        return urlsplit(referer).netloc == host
    return True


def is_local_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        if ipaddress.ip_address(client.host).is_loopback:
            return True
    except ValueError:
        return False
    # Opening the page through this machine's own network address still counts as local.
    server = request.scope.get("server")
    return bool(server) and server[0] == client.host


def is_local_bind(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def cookie_secure(request: Request) -> bool:
    return request.url.scheme == "https"


def is_public_hostname(value: str) -> bool:
    """A DNS name this process may list as its public address. Not an IP."""
    name = value.strip().lower().rstrip(".")
    if not name or name in _LOCAL_NAMES or len(name) > 253:
        return False
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        return False
    labels = name.split(".")
    if len(labels) < 2:
        return False
    return all(
        label
        and len(label) <= 63
        and label[0] != "-"
        and label[-1] != "-"
        and label.replace("-", "").isalnum()
        for label in labels
    )


def is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def network_address() -> str:
    """The address other devices use to reach this machine. Nothing is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()
