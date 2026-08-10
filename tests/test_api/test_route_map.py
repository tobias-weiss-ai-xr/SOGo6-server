"""Route-map smoke tests.

Instantiates the full Flask app and asserts that every registered rule in
the /api tree has a live view registered in ``app.view_functions`` and a
view class for the auth middleware to introspect (``public_access`` /
``accepted_content_types``).  Catches routing-level rot (typo'd/deleted
MethodView classes, half-registered blueprints) that the import smoke test
cannot see, because no single test exercises most endpoints.
"""
from __future__ import annotations

from app import create_app
from app.utils import constants as cs


def _api_rules(app) -> list:
    rules = []
    for rule in app.url_map.iter_rules():
        rule_str = rule.rule or ""
        if rule_str.startswith("/api/") and "static" not in (rule.endpoint or ""):
            rules.append(rule)
    return rules


def _view_class(app, endpoint: str):
    view = app.view_functions.get(endpoint or "")
    return getattr(view, "view_class", None)


def test_every_api_rule_has_a_resolved_view():
    app = create_app(cs.SOGO_OK)
    rules = _collect_rules(app)

    assert len(rules) >= 300  # catch mass de-registration regressions

    missing_view = []
    missing_class = []
    for rule in rules:
        if rule.endpoint not in app.view_functions:
            missing_view.append(rule.endpoint)
            continue
        if _view_class(app, rule.endpoint) is None:
            missing_class.append(rule.endpoint)

    assert not missing_view, f"rules without view_functions entry: {missing_view}"
    assert not missing_class, f"rules without view_class (auth middleware cannot introspect): {missing_class}"


def test_no_duplicate_route_method_combos():
    """Two rules with the same URL path AND the same HTTP method would
    shadow each other (only the first ever matches)."""
    app = create_app(cs.SOGO_OK)
    seen: dict[tuple, str] = {}
    conflicts = []
    for rule in _collect_rules(app):
        methods = frozenset(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        key = (rule.rule, methods)
        if key in seen:
            conflicts.append((key, seen[key], rule.endpoint))
        else:
            seen[key] = rule.endpoint

    assert not conflicts, f"duplicate (path, methods) routes shadow each other: {conflicts}"


def test_auth_middleware_endpoint_names_are_live():
    """The two by-name allowlists in app/__init__.py must match real endpoints
    (a stale name would silently kill that endpoint's anonymous access)."""
    app = create_app(cs.SOGO_OK)
    anon_names = {
        "user#Auth.v1_Auth.Auth.ApiAuthUserMode",
        "user#Auth.v1_Auth.Auth.ApiAuthUserLogin",
        "user#Auth.v1_Auth.Auth.ApiAuthUserCallback",
        "user#System.v1_System.System.ApiSystem",
        "admin#AdminAuth.v1_AdminAuth.AdminAuth.ApiAdminAuthLogin",
    }
    endpoints = set(app.view_functions)
    # every allowlist entry must exist (case-sensitive smorest endpoint names)
    stale = {n for n in anon_names if n not in endpoints}
    assert not stale, f"auth allowlist references non-existent endpoints: {stale}"


def _collect_rules(app):
    return [r for r in app.url_map.iter_rules() if r.rule and r.rule.startswith("/api/")]


def _view_class(app, endpoint: str):
    view = app.view_functions.get(endpoint)
    return getattr(view, "view_class", None)