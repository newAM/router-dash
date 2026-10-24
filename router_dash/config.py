import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(Exception):
    pass


DEFAULT_SESSION_FILE_DIR = "/var/lib/router-dash/sessions"
DEFAULT_LOG_LEVEL = "WARNING"
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

REQUIRED_KEYS = {
    "KEA_API_URL",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET_FILE",
    "OIDC_DISCOVERY_URL",
    "PUBLIC_URL",
    "ROLES_PATH",
    "SECRET_KEY_FILE",
}


@dataclass
class Config:
    secret_key: str
    kea_api_url: str
    kea_auth_user: str | None
    kea_auth_password: str | None
    oidc_client_id: str
    oidc_client_secret: str
    oidc_discovery_url: str
    public_url: str
    roles_path: list[str]
    viewer_role: str = "router_dash_users"
    session_file_dir: str = DEFAULT_SESSION_FILE_DIR
    session_cookie_samesite: str = "Strict"
    log_level: str = DEFAULT_LOG_LEVEL

    def to_flask_config(self) -> dict:
        return {
            "SECRET_KEY": self.secret_key,
            "KEA_API_URL": self.kea_api_url,
            "KEA_AUTH": (
                (self.kea_auth_user, self.kea_auth_password)
                if self.kea_auth_user is not None and self.kea_auth_password is not None
                else None
            ),
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "OIDC_DISCOVERY_URL": self.oidc_discovery_url,
            "PUBLIC_URL": self.public_url,
            "ROLES_PATH": self.roles_path,
            "VIEWER_ROLE": self.viewer_role,
            "SESSION_FILE_DIR": self.session_file_dir,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
        }


def load_config(path: str | Path) -> Config:
    path = Path(path)

    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError("config file must be a JSON object")

    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ConfigError(
            f"config file is missing required keys: {', '.join(sorted(missing))}"
        )

    secret_key_file = Path(data["SECRET_KEY_FILE"])
    if not secret_key_file.exists():
        raise ConfigError(f"secret key file not found: {secret_key_file}")

    secret_key = secret_key_file.read_text().strip()
    if not secret_key:
        raise ConfigError(f"secret key file is empty: {secret_key_file}")
    if len(secret_key) < 32:
        raise ConfigError("secret key must be at least 32 characters")

    oidc_client_secret_file = Path(data["OIDC_CLIENT_SECRET_FILE"])
    if not oidc_client_secret_file.exists():
        raise ConfigError(
            f"OIDC client secret file not found: {oidc_client_secret_file}"
        )

    oidc_client_secret = oidc_client_secret_file.read_text().strip()
    if not oidc_client_secret:
        raise ConfigError(
            f"OIDC client secret file is empty: {oidc_client_secret_file}"
        )

    kea_api_url = data["KEA_API_URL"]
    _validate_kea_api_url(kea_api_url)

    kea_auth_user = _read_optional_secret(data, "KEA_AUTH_USER_FILE", "KEA auth user")
    kea_auth_password = _read_optional_secret(
        data, "KEA_AUTH_PASSWORD_FILE", "KEA auth password"
    )
    if (kea_auth_user is None) != (kea_auth_password is None):
        raise ConfigError(
            "KEA_AUTH_USER_FILE and KEA_AUTH_PASSWORD_FILE must be set together"
        )
    if ":" in (kea_auth_user or ""):
        raise ConfigError("KEA auth user must not contain a ':'")

    roles_path = data.get("ROLES_PATH")
    if not isinstance(roles_path, list) or len(roles_path) == 0:
        raise ConfigError("ROLES_PATH must be a non-empty list of strings")
    if not all(isinstance(p, str) for p in roles_path):
        raise ConfigError("ROLES_PATH must be a non-empty list of strings")

    viewer_role = data.get("VIEWER_ROLE", "router_dash_users")
    if not isinstance(viewer_role, str) or not viewer_role:
        raise ConfigError("VIEWER_ROLE must be a non-empty string")

    session_file_dir = data.get("SESSION_FILE_DIR", DEFAULT_SESSION_FILE_DIR)
    if not isinstance(session_file_dir, str) or not session_file_dir.startswith("/"):
        raise ConfigError("SESSION_FILE_DIR must be an absolute path")

    session_cookie_samesite = data.get("SESSION_COOKIE_SAMESITE", "Strict")
    if session_cookie_samesite not in {"Strict", "Lax"}:
        raise ConfigError("SESSION_COOKIE_SAMESITE must be 'Strict' or 'Lax'")

    log_level = data.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    if not isinstance(log_level, str) or log_level.upper() not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"LOG_LEVEL must be one of: {', '.join(sorted(VALID_LOG_LEVELS))}"
        )
    log_level = log_level.upper()

    public_url = data["PUBLIC_URL"]
    _validate_https_url(public_url, "PUBLIC_URL")

    oidc_discovery_url = data["OIDC_DISCOVERY_URL"]
    _validate_https_url(oidc_discovery_url, "OIDC_DISCOVERY_URL")

    return Config(
        secret_key=secret_key,
        kea_api_url=kea_api_url,
        kea_auth_user=kea_auth_user,
        kea_auth_password=kea_auth_password,
        oidc_client_id=data["OIDC_CLIENT_ID"],
        oidc_client_secret=oidc_client_secret,
        oidc_discovery_url=oidc_discovery_url,
        public_url=public_url,
        roles_path=roles_path,
        viewer_role=viewer_role,
        session_file_dir=session_file_dir,
        session_cookie_samesite=session_cookie_samesite,
        log_level=log_level,
    )


def _validate_https_url(url: str, name: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"{name} must be a valid HTTPS URL")


def _read_optional_secret(data: dict, key: str, name: str) -> str | None:
    """Read an optional secret that must be provided as a file path."""
    path = data.get(key)
    if path is None:
        return None
    file = Path(path)
    if not file.exists():
        raise ConfigError(f"{name} file not found: {file}")
    content = file.read_text().strip()
    if not content:
        raise ConfigError(f"{name} file is empty: {file}")
    return content


def _validate_kea_api_url(url: object) -> None:
    if not isinstance(url, str):
        raise ConfigError("KEA_API_URL must be a valid HTTP URL")
    parsed = urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ConfigError("KEA_API_URL must be a valid HTTP URL")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("KEA_API_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ConfigError("KEA_API_URL must not contain a query or fragment")
    if parsed.path not in ("", "/"):
        raise ConfigError("KEA_API_URL must not contain a path")
    hostname = parsed.hostname
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is None or not address.is_loopback:
            raise ConfigError("KEA_API_URL must point at the loopback interface")
    try:
        port = parsed.port
    except ValueError:
        raise ConfigError("KEA_API_URL has an invalid port") from None
    if port is not None and not (0 < port < 65536):
        raise ConfigError("KEA_API_URL has an invalid port")
