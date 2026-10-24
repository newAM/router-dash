from typing import cast

from router_dash.auth import value_at_path


def test_value_at_path_list() -> None:
    data = {"claims": {"router_dash_roles": ["viewers", "admins"]}}
    assert value_at_path(data, ["claims", "router_dash_roles"]) == [
        "viewers",
        "admins",
    ]


def test_value_at_path_string() -> None:
    data = {"roles": "viewers"}
    assert value_at_path(data, ["roles"]) == ["viewers"]


def test_value_at_path_missing_key() -> None:
    assert value_at_path({"a": {}}, ["a", "b", "c"]) == []


def test_value_at_path_non_string_list() -> None:
    assert value_at_path({"roles": [1, 2]}, ["roles"]) == []


def test_value_at_path_non_str_scalar() -> None:
    assert value_at_path({"roles": 42}, ["roles"]) == []


def test_value_at_path_index_into_list() -> None:
    # The walker tolerates integer indices into JSON lists.
    # ROLES_PATH is always a list of strings at runtime; this exercises the
    # lookup internals directly.
    path = cast(list[str], ["roles", 0, "r"])
    assert value_at_path({"roles": [{"r": "viewers"}]}, path) == ["viewers"]


def test_keycloak_style_path() -> None:
    data = {"resource_access": {"router-dash": {"roles": ["viewers"]}}}
    assert value_at_path(data, ["resource_access", "router-dash", "roles"]) == [
        "viewers"
    ]
