import logging
import sys
from datetime import timedelta

from cachelib import FileSystemCache
from flask import Flask, Response
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

from router_dash.auth import auth_bp, init_oauth
from router_dash.config import Config
from router_dash.kea import KeaClient

csrf = CSRFProtect()

try:
    from systemd.journal import JournalHandler
except ImportError:  # pragma: no cover - non-Linux platforms
    JournalHandler = None


def _setup_logging(level: int = logging.WARNING) -> None:
    if JournalHandler is not None:
        handler = JournalHandler(SYSLOG_IDENTIFIER="router-dash")
    else:  # pragma: no cover - non-Linux platforms
        handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[{name}] {message}", style="{")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def create_app(config: Config) -> Flask:
    _setup_logging(logging.getLevelNamesMapping()[config.log_level])

    app = Flask(__name__)

    app.config.update(config.to_flask_config())

    app.config.update(
        {
            # The only request body the app accepts is the logout form,
            # which carries just a CSRF token.
            "MAX_CONTENT_LENGTH": 64 * 1024,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_NAME": "__Host-session",
            "SESSION_PERMANENT": True,
            "PERMANENT_SESSION_LIFETIME": timedelta(hours=24),
            "SESSION_TYPE": "cachelib",
            "SESSION_CACHELIB": FileSystemCache(
                config.session_file_dir,
                threshold=500,
                mode=0o600,
            ),
        }
    )
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Strict")

    app.extensions["kea_client"] = KeaClient(
        config.kea_api_url, auth=app.config["KEA_AUTH"]
    )

    Session(app)
    csrf.init_app(app)

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        # Instruct browsers to only connect over HTTPS for the next year.
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        # Explicitly allowlist only the resource types used,
        # deny everything else by default.
        response.headers["Content-Security-Policy"] = (
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
        )
        # Prevent browsers from MIME-sniffing responses away from the declared
        # content type, which can allow content injection attacks.
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Legacy framing protection for older browsers that predate CSP.
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent browsers and proxies from caching any responses.
        # Lease data reveals the devices on the local network and must not
        # be stored on disk or in shared caches.
        response.headers["Cache-Control"] = "no-store"
        # Allow the Referer header for same-origin navigations so that
        # Flask-WTF's CSRF referer check can validate form submissions,
        # while still preventing page URLs from leaking to third-party sites.
        response.headers["Referrer-Policy"] = "same-origin"
        # Deny access to unused sensitive browser APIs,
        # limiting the impact of any XSS vulnerability.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response

    app.register_blueprint(auth_bp)
    init_oauth(app)

    from router_dash.web import create_web_blueprint

    create_web_blueprint(app)

    return app
