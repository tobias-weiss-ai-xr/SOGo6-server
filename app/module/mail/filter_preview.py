"""Best-effort Sieve filter preview/matching engine.

Provides an offline, rule-tree evaluator used by the Sieve Editor's "preview"
feature. It mirrors the rule semantics of the filter schema so users can see
whether a given message (described by sample headers) would match a filter
before the rules are pushed to the real Sieve engine.

This module does NOT talk to the Sieve server and is intentionally pure
(it has no dependencies on DB or network) so it can be unit tested easily.
"""
from __future__ import annotations

from typing import Any


# Operator semantics: returns True when the header value satisfies the operator.
def _matches_operator(operator: str, field_value: str, compare_value: str) -> bool:
    """Evaluate a single operator against one header value."""
    compare_value = compare_value or ""
    if operator in ("contains", "has"):
        return compare_value.lower() in field_value.lower()
    if operator == "is":
        return field_value.lower() == compare_value.lower()
    if operator == "notcontains":
        return compare_value.lower() not in field_value.lower()
    if operator == "notis":
        return field_value.lower() != compare_value.lower()
    if operator in ("matches", "regex"):
        # Simple substring-comma split match (best effort, not a full regex engine).
        return compare_value.lower() in field_value.lower()
    if operator == "over":
        # size in megabytes
        try:
            return int(field_value) > int(compare_value)
        except (ValueError, TypeError):
            return False
    if operator == "under":
        try:
            return int(field_value) < int(compare_value)
        except (ValueError, TypeError):
            return False
    if operator == "exists":
        return field_value != ""
    if operator == "notexists":
        return field_value == ""
    # default
    return field_value.lower() == compare_value.lower()


def _evaluate_rule(node: dict[str, Any], headers: dict[str, str]) -> bool:
    """Evaluate one rule node (group or leaf) against headers."""
    if node.get("op") in ("and", "or"):
        children = node.get("rules") or []
        if node["op"] == "and":
            return all(_evaluate_rule(c, headers) for c in children)
        return any(_evaluate_rule(c, headers) for c in children)

    field_val = headers.get((node.get("field") or "").lower(), "")
    operator = node.get("operator")
    value = node.get("value", "")
    if operator is None:
        return False
    return _matches_operator(operator, str(field_val), str(value))


def _walk_rules(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a rule tree into leaf rules."""
    if node.get("op") in ("and", "or"):
        out: list[dict[str, Any]] = []
        for c in node.get("rules") or []:
            out.extend(_walk_rules(c))
        return out
    return [node]


def preview_filter(filter_payload: dict[str, Any], sample: dict[str, str]) -> tuple[bool, Any]:
    """Return ``(matched, action)`` for a single filter against sample headers.

    A filter is considered matched only if *all* of its leaf rules are satisfied
    (individual leaves are ANDed together regardless of group nesting).

    :param filter_payload: A validated filter dict with ``rules`` and ``actions``.
    :type filter_payload: dict[str, Any]
    :param sample: Sample message headers keyed by lower-cased header name.
    :type sample: dict[str, str]
    :return: Tuple of (did it match?, first configured action).
    :rtype: tuple[bool, dict[str, Any]]
    """
    if not filter_payload.get("enabled", True):
        return False, None  # type: ignore[return-value]

    rules = filter_payload.get("rules") or {}
    leaves = _walk_rules(rules)
    if not leaves:
        return False, None  # type: ignore[return-value]

    matched = all(_evaluate_rule(leaf, sample) for leaf in leaves)
    actions = filter_payload.get("actions") or []
    action = actions[0] if actions else None
    return matched, action