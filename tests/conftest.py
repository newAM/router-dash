from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient

from router_dash.app import create_app
from router_dash.config import Config
from router_dash.kea import Lease

SECRET_KEY = "test-secret-key-0123456789abcdef0123456"


class FakeKeaClient:
    def __init__(self, leases: list[Lease] | Exception | None = None) -> None:
        self._exc: Exception | None
        self._leases: list[Lease]
        if isinstance(leases, Exception):
            self._exc = leases
            self._leases = []
        else:
            self._exc = None
            self._leases = list(leases) if leases is not None else []

    def get_leases(self) -> list[Lease]:
        if self._exc is not None:
            raise self._exc
        return list(self._leases)


def make_lease(
    ip: str,
    mac: str = "52:54:00:12:34:56",
    hostname: str | None = "testclient",
    client_id: str | None = "01:52:54:00:12:34:56",
    expires_in: timedelta = timedelta(hours=1),
    state: int = 0,
    subnet_id: int = 1,
) -> Lease:
    return Lease(
        ip=ip,
        mac=mac.lower(),
        hostname=hostname,
        client_id=client_id,
        expires_at=datetime.now(UTC) + expires_in,
        state=state,
        subnet_id=subnet_id,
    )


@pytest.fixture(scope="session")
def config(tmp_path_factory: pytest.TempPathFactory) -> Config:
    return Config(
        secret_key=SECRET_KEY,
        kea_api_url="http://127.0.0.1:8000",
        kea_auth_user=None,
        kea_auth_password=None,
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        oidc_discovery_url="https://example.com/.well-known/openid-configuration",
        public_url="https://router-dash.example.com",
        roles_path=["roles"],
        session_file_dir=str(tmp_path_factory.mktemp("sessions")),
    )


@pytest.fixture(scope="session")
def app(config: Config) -> Generator[Flask]:
    flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    yield flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def authed_client(app: Flask) -> FlaskClient:
    """A test client with a pre-populated session simulating a logged-in user."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "test-user-sub",
            "email": "test@example.com",
            "name": "Test User",
            "roles": ["router_dash_users"],
        }
    return client


@pytest.fixture
def unroled_client(app: Flask) -> FlaskClient:
    """A test client with a logged-in user who has no valid roles."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "unroled-user-sub",
            "email": "unroled@example.com",
            "name": "Unroled User",
            "roles": [],
        }
    return client
