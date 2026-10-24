import json
from datetime import UTC, datetime
from typing import cast

import pytest
import requests

from router_dash.kea import (
    KeaClient,
    KeaError,
    ip_sort_key,
    mac_sort_key,
    parse_lease,
)

BASE_URL = "http://127.0.0.1:8000"


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def make_client(response: FakeResponse | Exception) -> tuple[KeaClient, FakeSession]:
    session = FakeSession(response)
    client = KeaClient(BASE_URL, session=cast("requests.Session", session))
    return client, session


def lease_payload(**overrides: object) -> dict:
    payload = {
        "ip-address": "192.168.1.100",
        "hw-address": "52:54:00:12:34:56",
        "hostname": "testclient",
        "client-id": "01:52:54:00:12:34:56",
        "cltt": 1730000000,
        "valid-lft": 3600,
        "state": 0,
        "subnet-id": 1,
    }
    payload.update(overrides)
    return payload


def kea_body(leases: list[object], result: int = 0) -> bytes:
    """Build a Kea response in the native (list-wrapped) format."""
    single = {"result": result, "arguments": {"leases": leases}}
    return json.dumps([single]).encode()


def kea_body_unwrapped(leases: list[object], result: int = 0) -> bytes:
    return json.dumps({"result": result, "arguments": {"leases": leases}}).encode()


def test_get_leases_parses_leases() -> None:
    client, session = make_client(FakeResponse(kea_body([lease_payload()])))
    leases = client.get_leases()
    assert len(leases) == 1
    lease = leases[0]
    assert lease.ip == "192.168.1.100"
    assert lease.mac == "52:54:00:12:34:56"
    assert lease.hostname == "testclient"
    assert lease.client_id == "01:52:54:00:12:34:56"
    assert lease.expires_at == datetime.fromtimestamp(1730000000 + 3600, tz=UTC)
    assert lease.state == 0
    assert lease.state_name == "active"
    assert lease.subnet_id == 1
    assert session.calls == [
        {
            "url": BASE_URL + "/",
            "json": {"command": "lease4-get-all"},
            "headers": None,
            "timeout": (2.0, 5.0),
        }
    ]


def test_get_leases_sends_basic_auth() -> None:
    import base64

    session = FakeSession(FakeResponse(kea_body([])))
    client = KeaClient(
        BASE_URL,
        auth=("router-dash", "secret"),
        session=cast("requests.Session", session),
    )
    client.get_leases()
    expected = "Basic " + base64.b64encode(b"router-dash:secret").decode()
    assert session.calls[0]["headers"] == {"Authorization": expected}


def test_get_leases_normalizes_mac_case() -> None:
    client, _ = make_client(
        FakeResponse(kea_body([lease_payload(**{"hw-address": "AA:BB:CC:DD:EE:FF"})]))
    )
    assert client.get_leases()[0].mac == "aa:bb:cc:dd:ee:ff"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ip-address", 42),
        ("ip-address", "not-an-ip"),
        ("hw-address", None),
        ("hw-address", "zz:54:00:12:34:56"),
        ("hw-address", "52:54:00:12:34"),
        ("hw-address", "52-54-00-12-34-56"),
        ("hostname", 42),
        ("client-id", 42),
        ("cltt", "1730000000"),
        ("cltt", True),
        ("valid-lft", None),
        ("state", "0"),
        ("subnet-id", None),
    ],
)
def test_malformed_lease_fields_rejected(field: str, value: object) -> None:
    with pytest.raises(KeaError):
        parse_lease(lease_payload(**{field: value}))


def test_lease_out_of_range_expiry_rejected() -> None:
    with pytest.raises(KeaError, match="out-of-range expiry"):
        parse_lease(lease_payload(cltt=2**60, **{"valid-lft": 0}))
    with pytest.raises(KeaError, match="out-of-range expiry"):
        parse_lease(lease_payload(cltt=-(2**60), **{"valid-lft": 0}))


def test_lease_string_fields_capped() -> None:
    with pytest.raises(KeaError):
        parse_lease(lease_payload(hostname="x" * 257))


def test_optional_fields_default_to_none() -> None:
    lease = parse_lease(lease_payload(**{"hostname": "", "client-id": None}))
    assert lease.hostname is None
    assert lease.client_id is None


def test_state_names() -> None:
    for state, name in [(0, "active"), (1, "declined"), (2, "expired-reclaimed")]:
        lease = parse_lease(lease_payload(state=state))
        assert lease.state_name == name
    assert parse_lease(lease_payload(state=99)).state_name == "unknown (99)"


def test_get_leases_accepts_unwrapped_response() -> None:
    client, _ = make_client(FakeResponse(kea_body_unwrapped([lease_payload()])))
    assert len(client.get_leases()) == 1


@pytest.mark.parametrize(
    "body",
    [
        # empty response list
        b"[]",
        # multiple daemon responses
        json.dumps([{"result": 0}, {"result": 0}]).encode(),
        # list-wrapped garbage
        b"[1, 2, 3]",
    ],
)
def test_get_leases_rejects_malformed_response_list(body: bytes) -> None:
    client, _ = make_client(FakeResponse(body))
    with pytest.raises(KeaError, match="malformed response"):
        client.get_leases()


def test_get_leases_rejects_nonzero_result() -> None:
    client, _ = make_client(FakeResponse(kea_body([], result=1)))
    with pytest.raises(KeaError, match="result 1"):
        client.get_leases()


def test_get_leases_rejects_missing_result() -> None:
    client, _ = make_client(FakeResponse(b'{"arguments": {}}'))
    with pytest.raises(KeaError, match="result code"):
        client.get_leases()


def test_get_leases_rejects_invalid_json() -> None:
    client, _ = make_client(FakeResponse(b"<html>not json</html>"))
    with pytest.raises(KeaError, match="invalid JSON"):
        client.get_leases()


def test_get_leases_rejects_unauthorized() -> None:
    client, _ = make_client(FakeResponse(b"{}", status_code=401))
    with pytest.raises(KeaError, match="rejected the credentials"):
        client.get_leases()


def test_get_leases_rejects_http_error() -> None:
    client, _ = make_client(FakeResponse(b"{}", status_code=500))
    with pytest.raises(KeaError, match="HTTP status 500"):
        client.get_leases()


def test_get_leases_rejects_oversized_response() -> None:
    client = KeaClient(
        BASE_URL,
        max_response_bytes=16,
        session=cast(
            "requests.Session",
            FakeSession(FakeResponse(kea_body([lease_payload()]))),
        ),
    )
    with pytest.raises(KeaError, match="too large"):
        client.get_leases()


def test_get_leases_rejects_non_list_leases() -> None:
    client, _ = make_client(FakeResponse(b'{"result": 0, "arguments": {"leases": 42}}'))
    with pytest.raises(KeaError, match="lease list"):
        client.get_leases()


def test_get_leases_rejects_non_dict_lease_entries() -> None:
    client, _ = make_client(FakeResponse(kea_body(["nope"])))
    with pytest.raises(KeaError, match="malformed lease"):
        client.get_leases()


def test_get_leases_wraps_connection_errors() -> None:
    client, _ = make_client(requests.ConnectionError("connection refused"))
    with pytest.raises(KeaError, match="failed to reach the DHCP server"):
        client.get_leases()


def test_get_leases_empty() -> None:
    client, _ = make_client(FakeResponse(kea_body([])))
    assert client.get_leases() == []


def test_url_normalizes_trailing_slash() -> None:
    client = KeaClient("http://127.0.0.1:8000/")
    session = FakeSession(FakeResponse(kea_body([])))
    client._session = cast("requests.Session", session)
    client.get_leases()
    assert session.calls[0]["url"] == BASE_URL + "/"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000",
        "http://192.168.1.1:8000",
        "http://10.0.0.1:8000",
        "http://kea.internal:8000",
        "http://user:pass@127.0.0.1:8000",
        "not-a-url",
        "",
    ],
)
def test_client_rejects_non_loopback_urls(url: str) -> None:
    with pytest.raises(KeaError, match="KEA_API_URL"):
        KeaClient(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://[::1]:8000",
        "http://127.0.0.1",
    ],
)
def test_client_accepts_loopback_urls(url: str) -> None:
    KeaClient(url)


def test_sort_keys() -> None:
    a = parse_lease(
        lease_payload(
            **{"ip-address": "192.168.1.2", "hw-address": "52:54:00:00:00:02"}
        )
    )
    b = parse_lease(
        lease_payload(
            **{"ip-address": "192.168.1.10", "hw-address": "52:54:00:00:00:0a"}
        )
    )
    # Integer ordering, not lexical ("10" < "2" lexically).
    assert ip_sort_key(a) < ip_sort_key(b)
    assert mac_sort_key(a) < mac_sort_key(b)
