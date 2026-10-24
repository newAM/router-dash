import functools
import importlib.metadata
from collections.abc import Callable
from datetime import UTC, datetime

from authlib.integrations.base_client import OAuthError
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from router_dash.auth import UserSession, current_user, oauth
from router_dash.kea import (
    KeaError,
    Lease,
    expires_sort_key,
    ip_sort_key,
    mac_sort_key,
)


def _project_url() -> str:
    """Return the repository URL from the installed package metadata.

    PEP 621 URLs are stored as repeated "Project-URL: Key, Value" headers,
    so the entries are parsed into a mapping and indexed by key.
    """
    urls = dict(
        entry.partition(", ")[::2]
        for entry in importlib.metadata.metadata("router-dash").get_all(
            "Project-URL", []
        )
    )
    return urls["Repository"]


# Fail fast at startup: the footer must not render an arbitrary URL.
_REPO_URL = _project_url()

web_bp = Blueprint("web", __name__)


def _has_required_role(user: UserSession) -> bool:
    roles = user.get("roles", [])
    viewer_role = current_app.config["VIEWER_ROLE"]
    return viewer_role in roles


def _role_denied_response() -> tuple[str, int]:
    viewer_role = current_app.config["VIEWER_ROLE"]
    message = (
        f"Permission denied. Contact your system administrator and request "
        f"the {viewer_role!r} role."
    )
    return render_template("error.html", code=403, message=message), 403


def require_web_auth(
    f: Callable[..., ResponseReturnValue],
) -> Callable[..., ResponseReturnValue]:
    """Decorator that injects the authenticated user as the first argument.

    Returns an HTML 404 error page if no session user is found, or a 403
    permission denied page if the user lacks the required role.
    """

    @functools.wraps(f)
    def wrapper(*args: object, **kwargs: object) -> ResponseReturnValue:
        user = current_user()
        if user is None:
            return render_template("error.html", code=404, message="Not found"), 404
        if not _has_required_role(user):
            return _role_denied_response()
        return f(user, *args, **kwargs)

    return wrapper


def _lease_row(lease: Lease, now: datetime) -> dict[str, object]:
    """Pair each display value with its canonical sort value (`*_v`)."""
    return {
        "ip": lease.ip,
        "ip_v": ip_sort_key(lease),
        "hostname": lease.hostname or "—",
        "hostname_v": lease.hostname or "",
        "mac": lease.mac,
        "mac_v": mac_sort_key(lease),
        "client_id": lease.client_id or "—",
        "client_id_v": lease.client_id or "",
        "state": lease.state_name,
        "state_v": lease.state,
        "subnet": lease.subnet_id,
        "subnet_v": lease.subnet_id,
        "expires": lease.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        "expires_iso": lease.expires_at.isoformat(),
        "expires_class": "expired" if lease.expires_at < now else "",
        "expires_v": expires_sort_key(lease),
    }


def _to_rows(leases: list[Lease]) -> list[dict[str, object]]:
    """Flatten leases into template rows for the lease table."""
    now = datetime.now(UTC)
    return [_lease_row(lease, now) for lease in leases]


def create_web_blueprint(app: Flask) -> None:
    @web_bp.context_processor
    def inject_template_context() -> dict[str, str]:
        return {"repo_url": _REPO_URL}

    @web_bp.route("/")
    def index() -> ResponseReturnValue:
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login"))
        if not _has_required_role(user):
            return _role_denied_response()

        try:
            leases = current_app.extensions["kea_client"].get_leases()
        except KeaError as e:
            current_app.logger.error("event=kea_error error=%r", e)
            return (
                render_template(
                    "error.html",
                    code=503,
                    message="The DHCP server is currently unreachable.",
                ),
                503,
            )

        return render_template(
            "index.html",
            user=user,
            rows=_to_rows(sorted(leases, key=ip_sort_key)),
        )

    @web_bp.route("/logged-out")
    def logged_out() -> ResponseReturnValue:
        if request.args.get("state"):
            try:
                oauth.oidc.validate_logout_response()
            except OAuthError:
                current_app.logger.warning(
                    "event=logout_validation_failed", exc_info=True
                )
                return render_template(
                    "error.html", code=400, message="Logout validation failed"
                ), 400
        return render_template("logged_out.html")

    @web_bp.route("/healthz")
    def healthz() -> ResponseReturnValue:
        return {"status": "ok"}

    @web_bp.route("/robots.txt")
    def robots_txt() -> ResponseReturnValue:
        content = "User-agent: *\nDisallow: /\n"
        return Response(content, mimetype="text/plain")

    def forbidden(_e: Exception) -> ResponseReturnValue:
        return render_template("error.html", code=403, message="Forbidden"), 403

    def not_found(_e: Exception) -> ResponseReturnValue:
        return render_template("error.html", code=404, message="Not found"), 404

    def server_error(_e: Exception) -> ResponseReturnValue:
        return render_template(
            "error.html", code=500, message="Internal server error"
        ), 500

    # App-level handlers so unknown URLs outside of blueprint routes also
    # render the styled error page.
    app.register_error_handler(403, forbidden)
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, server_error)

    app.register_blueprint(web_bp)
