import json
from pathlib import Path

import pytest

from router_dash.config import ConfigError, load_config

SECRET_KEY = "test-secret-key-0123456789abcdef0123456"


def write_config(tmp_path: Path, data: dict, **files: str) -> Path:
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path


def valid_data(tmp_path: Path) -> dict:
    return {
        "SECRET_KEY_FILE": str(tmp_path / "secret_key"),
        "KEA_API_URL": "http://127.0.0.1:8000",
        "OIDC_CLIENT_ID": "router-dash",
        "OIDC_CLIENT_SECRET_FILE": str(tmp_path / "oidc_secret"),
        "OIDC_DISCOVERY_URL": "https://kanidm.example.com/oauth2/openid/router-dash/.well-known/openid-configuration",
        "PUBLIC_URL": "https://router-dash.example.com",
        "ROLES_PATH": ["router_dash_roles"],
    }


def test_load_valid_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        valid_data(tmp_path),
        secret_key=SECRET_KEY,
        oidc_secret="oidc-secret",
    )
    config = load_config(path)
    assert config.secret_key == SECRET_KEY
    assert config.kea_api_url == "http://127.0.0.1:8000"
    assert config.kea_auth_user is None
    assert config.kea_auth_password is None
    assert config.oidc_client_id == "router-dash"
    assert config.oidc_client_secret == "oidc-secret"
    assert config.public_url == "https://router-dash.example.com"
    assert config.roles_path == ["router_dash_roles"]
    assert config.viewer_role == "router_dash_users"
    assert config.session_cookie_samesite == "Strict"
    assert config.log_level == "WARNING"
    assert config.to_flask_config()["KEA_AUTH"] is None


def test_load_config_with_kea_auth(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["KEA_AUTH_USER_FILE"] = str(tmp_path / "kea_user")
    data["KEA_AUTH_PASSWORD_FILE"] = str(tmp_path / "kea_password")
    path = write_config(
        tmp_path,
        data,
        secret_key=SECRET_KEY,
        oidc_secret="oidc-secret",
        kea_user="router-dash",
        kea_password="kea-secret\n",
    )
    config = load_config(path)
    assert config.kea_auth_user == "router-dash"
    assert config.kea_auth_password == "kea-secret"
    assert config.to_flask_config()["KEA_AUTH"] == ("router-dash", "kea-secret")


def test_kea_auth_files_must_be_set_together(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["KEA_AUTH_USER_FILE"] = str(tmp_path / "kea_user")
    path = write_config(
        tmp_path,
        data,
        secret_key=SECRET_KEY,
        oidc_secret="oidc-secret",
        kea_user="router-dash",
    )
    with pytest.raises(ConfigError, match="must be set together"):
        load_config(path)


def test_kea_auth_user_must_not_contain_colon(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["KEA_AUTH_USER_FILE"] = str(tmp_path / "kea_user")
    data["KEA_AUTH_PASSWORD_FILE"] = str(tmp_path / "kea_password")
    path = write_config(
        tmp_path,
        data,
        secret_key=SECRET_KEY,
        oidc_secret="oidc-secret",
        kea_user="user:pass",
        kea_password="kea-secret",
    )
    with pytest.raises(ConfigError, match="must not contain a ':'"):
        load_config(path)


def test_kea_auth_missing_file(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["KEA_AUTH_USER_FILE"] = str(tmp_path / "nonexistent")
    data["KEA_AUTH_PASSWORD_FILE"] = str(tmp_path / "nonexistent2")
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="not found"):
        load_config(path)


def test_kea_auth_empty_file(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["KEA_AUTH_USER_FILE"] = str(tmp_path / "kea_user")
    data["KEA_AUTH_PASSWORD_FILE"] = str(tmp_path / "kea_password")
    path = write_config(
        tmp_path,
        data,
        secret_key=SECRET_KEY,
        oidc_secret="oidc-secret",
        kea_user="",
        kea_password="kea-secret",
    )
    with pytest.raises(ConfigError, match="file is empty"):
        load_config(path)


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "nonexistent.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_not_an_object(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ConfigError, match="must be a JSON object"):
        load_config(path)


def test_missing_required_keys(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    del data["PUBLIC_URL"]
    del data["KEA_API_URL"]
    path = write_config(tmp_path, data, secret_key=SECRET_KEY, oidc_secret="s")
    with pytest.raises(ConfigError, match="missing required keys") as e:
        load_config(path)
    assert "KEA_API_URL" in str(e.value)
    assert "PUBLIC_URL" in str(e.value)


def test_missing_secret_key_file(tmp_path: Path) -> None:
    path = write_config(tmp_path, valid_data(tmp_path), oidc_secret="oidc-secret")
    with pytest.raises(ConfigError, match="secret key file not found"):
        load_config(path)


def test_empty_secret_key(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, valid_data(tmp_path), secret_key="", oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="secret key file is empty"):
        load_config(path)


def test_short_secret_key(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, valid_data(tmp_path), secret_key="too-short", oidc_secret="s"
    )
    with pytest.raises(ConfigError, match="at least 32 characters"):
        load_config(path)


def test_missing_oidc_secret_file(tmp_path: Path) -> None:
    path = write_config(tmp_path, valid_data(tmp_path), secret_key=SECRET_KEY)
    with pytest.raises(ConfigError, match="OIDC client secret file not found"):
        load_config(path)


def test_empty_oidc_secret(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, valid_data(tmp_path), secret_key=SECRET_KEY, oidc_secret=""
    )
    with pytest.raises(ConfigError, match="OIDC client secret file is empty"):
        load_config(path)


@pytest.mark.parametrize(
    "url_key",
    ["PUBLIC_URL", "OIDC_DISCOVERY_URL"],
)
def test_non_https_urls_rejected(tmp_path: Path, url_key: str) -> None:
    data = valid_data(tmp_path)
    data[url_key] = "http://example.com"
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match=f"{url_key} must be a valid HTTPS URL"):
        load_config(path)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000",
        "http://example.com",
        "http://192.168.1.1:8000",
        "http://user:pass@127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000?query=1",
        "http://127.0.0.1:99999",
        "not a url",
        "",
        42,
    ],
)
def test_invalid_kea_api_url(tmp_path: Path, url: object) -> None:
    data = valid_data(tmp_path)
    data["KEA_API_URL"] = url
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="KEA_API_URL"):
        load_config(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://[::1]:8000",
        "http://127.0.0.1",
    ],
)
def test_valid_kea_api_urls(tmp_path: Path, url: str) -> None:
    data = valid_data(tmp_path)
    data["KEA_API_URL"] = url
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    assert load_config(path).kea_api_url == url


@pytest.mark.parametrize(
    "roles_path",
    [None, [], [1, 2], "roles"],
)
def test_invalid_roles_path(tmp_path: Path, roles_path: object) -> None:
    data = valid_data(tmp_path)
    data["ROLES_PATH"] = roles_path
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="ROLES_PATH"):
        load_config(path)


def test_invalid_viewer_role(tmp_path: Path) -> None:
    data = valid_data(tmp_path)
    data["VIEWER_ROLE"] = ""
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="VIEWER_ROLE"):
        load_config(path)


@pytest.mark.parametrize("samesite", ["strict", "None", "none", 3])
def test_invalid_samesite(tmp_path: Path, samesite: object) -> None:
    data = valid_data(tmp_path)
    data["SESSION_COOKIE_SAMESITE"] = samesite
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="SESSION_COOKIE_SAMESITE"):
        load_config(path)


@pytest.mark.parametrize("level", ["VERBOSE", 5, None])
def test_invalid_log_level(tmp_path: Path, level: object) -> None:
    data = valid_data(tmp_path)
    data["LOG_LEVEL"] = level
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_config(path)


@pytest.mark.parametrize("session_dir", ["relative/path", 42])
def test_invalid_session_file_dir(tmp_path: Path, session_dir: object) -> None:
    data = valid_data(tmp_path)
    data["SESSION_FILE_DIR"] = session_dir
    path = write_config(
        tmp_path, data, secret_key=SECRET_KEY, oidc_secret="oidc-secret"
    )
    with pytest.raises(ConfigError, match="SESSION_FILE_DIR"):
        load_config(path)
