"""Outbound URL policy for source connections (SSRF defence).

A connection URL is accepted only if its host:port is on the operator's allowlist
(UETL_SPICE_ALLOWED_HOSTS, comma separated "host:port") AND every address it resolves to is
usable. Loopback, link-local (incl. the cloud metadata address), multicast and unspecified
addresses are refused even when allow-listed. Private ranges (RFC 1918) are allowed only
through the allowlist, because the real SPICE host is on the corporate network.

Re-validate with `resolve_pinned` at connect time and connect to the returned IP, so a DNS
answer that changes after saving (rebinding) cannot redirect the request.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from . import config


class PolicyError(ValueError):
    pass


def allowed_hosts():
    raw = config.get("UETL_SPICE_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _bad(ip):
    return ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


def parse(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise PolicyError("scheme must be http or https")
    if u.username or u.password:
        raise PolicyError("credentials in the URL are not allowed")
    if not u.hostname or u.fragment or u.query:
        raise PolicyError("URL must be scheme://host[:port][/path] only")
    port = u.port or (443 if u.scheme == "https" else 80)
    return u, u.hostname.lower(), port


def resolve_pinned(url, allow=None, resolver=None):
    """Validate `url` and return (ip, port) to connect to. Raises PolicyError."""
    u, host, port = parse(url)
    allow = allowed_hosts() if allow is None else allow
    if f"{host}:{port}" not in allow:
        raise PolicyError("host is not on the allowlist (UETL_SPICE_ALLOWED_HOSTS)")
    resolver = resolver or socket.getaddrinfo  # looked up at call time so it can be substituted
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise PolicyError("host does not resolve") from None
    ips = {ipaddress.ip_address(i[4][0]) for i in infos}
    if not ips or any(_bad(ip) for ip in ips):
        raise PolicyError("host resolves to a forbidden address")
    return str(sorted(ips, key=str)[0]), port
