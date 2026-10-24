"""Client for the Kea DHCPv4 HTTP control socket.

Kea 3.x serves its command API (formerly exposed by the separate Control
Agent) over HTTP on a TCP socket, restricted to the loopback interface by
deployment convention and optionally protected with HTTP basic
authentication.
"""

import base64
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import requests

DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_READ_TIMEOUT = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MiB

MAX_STRING_LENGTH = 256

# Six colon-separated lowercase hex octets, e.g. 52:54:00:12:34:56.
_MAC_RE = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")

LEASE_STATES = {
    0: "active",
    1: "declined",
    2: "expired-reclaimed",
}


class KeaError(Exception):
    """Raised when the Kea control socket is unreachable or misbehaves."""


@dataclass(frozen=True)
class Lease:
    ip: str
    mac: str
    hostname: str | None
    client_id: str | None
    expires_at: datetime
    state: int
    subnet_id: int

    @property
    def state_name(self) -> str:
        return LEASE_STATES.get(self.state, f"unknown ({self.state})")


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise KeaError(f"lease field {field!r} is not a string")
    if len(value) > MAX_STRING_LENGTH:
        raise KeaError(f"lease field {field!r} is too long")
    return value


def _require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise KeaError(f"lease field {field!r} is not an integer")
    return value


def parse_lease(raw: dict[str, Any]) -> Lease:
    ip = _require_str(raw.get("ip-address"), "ip-address")
    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError as e:
        raise KeaError(f"lease has an invalid IPv4 address: {ip!r}") from e

    mac = _require_str(raw.get("hw-address"), "hw-address").lower()
    if _MAC_RE.fullmatch(mac) is None:
        raise KeaError(f"lease has an invalid MAC address: {mac!r}")

    hostname = raw.get("hostname")
    hostname = None if not hostname else _require_str(hostname, "hostname")

    client_id = raw.get("client-id")
    client_id = None if not client_id else _require_str(client_id, "client-id")

    cltt = _require_int(raw.get("cltt"), "cltt")
    valid_lft = _require_int(raw.get("valid-lft"), "valid-lft")

    try:
        expires_at = datetime.fromtimestamp(cltt + valid_lft, tz=UTC)
    except (ValueError, OverflowError, OSError) as e:
        raise KeaError("lease has an out-of-range expiry time") from e

    return Lease(
        ip=ip,
        mac=mac,
        hostname=hostname,
        client_id=client_id,
        expires_at=expires_at,
        state=_require_int(raw.get("state"), "state"),
        subnet_id=_require_int(raw.get("subnet-id"), "subnet-id"),
    )


def ip_sort_key(lease: Lease) -> int:
    return int(ipaddress.IPv4Address(lease.ip))


def mac_sort_key(lease: Lease) -> int:
    return int(lease.mac.replace(":", ""), 16)


def expires_sort_key(lease: Lease) -> int:
    return int(lease.expires_at.timestamp())


def _basic_auth_header(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


class KeaClient:
    """Minimal client for Kea's HTTP control socket."""

    def __init__(
        self,
        base_url: str,
        *,
        auth: tuple[str, str] | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        session: requests.Session | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname:
            raise KeaError("KEA_API_URL must be a valid HTTP URL")
        try:
            addr = ipaddress.ip_address(parts.hostname)
        except ValueError:
            addr = None
        if parts.hostname != "localhost" and (addr is None or not addr.is_loopback):
            raise KeaError("KEA_API_URL must point at the loopback interface")
        if parts.username is not None or parts.password is not None:
            raise KeaError("KEA_API_URL must not contain credentials")

        self._url = base_url.rstrip("/") + "/"
        self._headers = {"Authorization": _basic_auth_header(*auth)} if auth else None
        self._timeouts = (connect_timeout, read_timeout)
        self._max_response_bytes = max_response_bytes
        self._session = session if session is not None else requests.Session()

    def get_leases(self) -> list[Lease]:
        try:
            response = self._session.post(
                self._url,
                json={"command": "lease4-get-all"},
                timeout=self._timeouts,
                headers=self._headers,
            )
        except requests.RequestException as e:
            raise KeaError("failed to reach the DHCP server") from e

        if response.status_code == 401:
            raise KeaError("the DHCP server rejected the credentials")
        if response.status_code != 200:
            raise KeaError(f"DHCP server returned HTTP status {response.status_code}")
        if len(response.content) > self._max_response_bytes:
            raise KeaError("DHCP server response is too large")

        try:
            body = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise KeaError("DHCP server returned invalid JSON") from e

        # Kea's native HTTP control socket emulates the old Control Agent
        # and wraps the answer of the single daemon in a list.
        if isinstance(body, list):
            if len(body) != 1 or not isinstance(body[0], dict):
                raise KeaError("DHCP server returned a malformed response")
            body = body[0]

        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, int):
            raise KeaError("DHCP server response has no result code")
        if result != 0:
            raise KeaError(f"DHCP server command failed (result {result})")

        leases = body.get("arguments", {}).get("leases", [])
        if not isinstance(leases, list):
            raise KeaError("DHCP server response has no lease list")

        parsed = []
        for entry in leases:
            if not isinstance(entry, dict):
                raise KeaError("DHCP server returned a malformed lease")
            parsed.append(parse_lease(entry))
        return parsed
