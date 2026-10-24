import email.message
import importlib.metadata

import pytest

from router_dash import web


def _metadata(*project_urls: tuple[str, str]) -> email.message.Message:
    msg = email.message.Message()
    for key, value in project_urls:
        msg["Project-URL"] = f"{key}, {value}"
    return msg


def test_project_url_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        importlib.metadata,
        "metadata",
        lambda _: _metadata(("Repository", "https://example.com/router-dash")),
    )
    assert web._project_url() == "https://example.com/router-dash"


def test_project_url_missing_repository_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        importlib.metadata,
        "metadata",
        lambda _: _metadata(("Changelog", "https://example.com/changelog")),
    )
    with pytest.raises(KeyError, match="Repository"):
        web._project_url()


def test_project_url_fails_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(name: str) -> importlib.metadata.PackageMetadata:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "metadata", raise_not_found)
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        web._project_url()
