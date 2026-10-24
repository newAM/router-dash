from datetime import timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient

from router_dash.kea import KeaError
from tests.conftest import FakeKeaClient, make_lease

LEASES = [
    make_lease(ip="192.168.2.10", hostname="alpha"),
    make_lease(ip="192.168.2.2", hostname="beta"),
    make_lease(ip="192.168.2.100", hostname="gamma", expires_in=timedelta(hours=-1)),
]


@pytest.fixture
def kea_client(app: Flask) -> FakeKeaClient:
    client = FakeKeaClient(LEASES)
    app.extensions["kea_client"] = client
    return client


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self'; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "upgrade-insecure-requests"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


def test_unauthenticated_index_redirects_to_login(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_healthz(client: FlaskClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_robots_txt(client: FlaskClient) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"


def test_security_headers_on_all_responses(client: FlaskClient) -> None:
    for path in ["/", "/healthz", "/robots.txt", "/static/style.css", "/nope"]:
        response = client.get(path)
        for header, expected in SECURITY_HEADERS.items():
            assert response.headers.get(header) == expected, f"{path}: {header}"


def test_static_sort_js_served(client: FlaskClient) -> None:
    response = client.get("/static/sort.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["Content-Type"]


def test_index_requires_role(unroled_client: FlaskClient) -> None:
    response = unroled_client.get("/")
    assert response.status_code == 403
    assert "router_dash_users" in response.text


def test_index_renders_leases(
    authed_client: FlaskClient, kea_client: FakeKeaClient
) -> None:
    response = authed_client.get("/")
    assert response.status_code == 200
    for lease in LEASES:
        assert lease.ip in response.text
        assert (lease.hostname or "") in response.text
        assert lease.mac in response.text

    # Table markup for progressive sorting enhancement.
    assert '<table class="sortable">' in response.text
    assert 'aria-sort="ascending"' in response.text
    assert 'data-v="' in response.text


def test_index_sorted_by_ip(
    authed_client: FlaskClient, kea_client: FakeKeaClient
) -> None:
    response = authed_client.get("/")
    body = response.get_data(as_text=True)
    # Integer ordering: 192.168.2.2 < 192.168.2.10 < 192.168.2.100.
    assert body.index("192.168.2.2") < body.index("192.168.2.10")
    assert body.index("192.168.2.10") < body.index("192.168.2.100")


def test_index_marks_expired_leases(
    authed_client: FlaskClient, kea_client: FakeKeaClient
) -> None:
    response = authed_client.get("/")
    assert 'class="expired"' in response.text


def test_index_data_v_sort_values(
    authed_client: FlaskClient, kea_client: FakeKeaClient
) -> None:
    response = authed_client.get("/")
    body = response.get_data(as_text=True)
    # 192.168.2.2 as a 32-bit integer.
    assert f'data-v="{(192 << 24) + (168 << 16) + (2 << 8) + 2}"' in body


def test_index_empty_lease_table(
    authed_client: FlaskClient, kea_client: FakeKeaClient
) -> None:
    kea_client._leases = []
    response = authed_client.get("/")
    assert response.status_code == 200
    assert "No leases." in response.text


def test_index_kea_unreachable(authed_client: FlaskClient, app: Flask) -> None:
    app.extensions["kea_client"] = FakeKeaClient(KeaError("boom"))
    response = authed_client.get("/")
    assert response.status_code == 503
    assert "DHCP server is currently unreachable" in response.text


def test_logout_requires_post(authed_client: FlaskClient) -> None:
    response = authed_client.get("/logout")
    assert response.status_code == 405


def test_logout_requires_csrf(client: FlaskClient) -> None:
    response = client.post("/logout")
    assert response.status_code == 400


def test_oversized_request_body_rejected(client: FlaskClient) -> None:
    response = client.post("/logout", data={"blob": "a" * (70 * 1024)})
    assert response.status_code == 413


def test_not_found_renders_error_page(client: FlaskClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "<h1>404</h1>" in response.text


def test_session_cookie_attributes(app: Flask) -> None:
    app.extensions["kea_client"] = FakeKeaClient([])
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "cookie-test-sub",
            "roles": ["router_dash_users"],
        }
    # Rendering the page generates a CSRF token, which writes the session
    # and emits the session cookie.
    response = client.get("/")
    cookie = response.headers.get("Set-Cookie", "")
    assert cookie.startswith("__Host-session=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=" in cookie
