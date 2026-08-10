"""Unit tests for the sieve filter preview/matching engine.

These tests are pure (no DB, no network, no fixtures) and can run anywhere.
"""
import pytest

from app.module.mail.filter_preview import (
    _matches_operator,
    _evaluate_rule,
    preview_filter,
)


class TestOperatorMatching:
    @pytest.mark.parametrize(
        "operator,value,compare,expected",
        [
            ("contains", "Hello World", "hello", True),
            ("contains", "Hello World", "nope", False),
            ("has", "Hello World", "world", True),
            ("is", "exact", "exact", True),
            ("is", "Exact", "exact", True),
            ("is", "other", "exact", False),
            ("notcontains", "Hello World", "nope", True),
            ("notcontains", "Hello World", "hello", False),
            ("notis", "other", "exact", True),
            ("notis", "exact", "exact", False),
            ("exists", "hasvalue", "", True),
            ("notexists", "", "", True),
            ("notexists", "x", "", False),
            # numeric size operators
            ("over", "5", "3", True),
            ("over", "2", "3", False),
            ("under", "2", "3", True),
            ("under", "5", "3", False),
        ],
    )
    def test_operator_semantics(self, operator, value, compare, expected):
        assert _matches_operator(operator, value, compare) is expected


class TestRuleEvaluation:
    def test_leaf_match(self):
        node = {"field": "subject", "operator": "contains", "value": "invoice"}
        assert _evaluate_rule(node, {"subject": "Your invoice"}) is True
        assert _evaluate_rule(node, {"subject": "Hello"}) is False

    def test_case_insensitive_field(self):
        node = {"field": "From", "operator": "contains", "value": "ceo"}
        assert _evaluate_rule(node, {"from": "ceo@example.com"}) is True

    def test_missing_header_not_match(self):
        node = {"field": "to", "operator": "is", "value": "x"}
        assert _evaluate_rule(node, {"subject": "ignored"}) is False

    def test_and_group(self):
        node = {
            "op": "and",
            "rules": [
                {"field": "from", "operator": "contains", "value": "ceo"},
                {"field": "subject", "operator": "contains", "value": "urgent"},
            ],
        }
        assert _evaluate_rule(node, {"from": "ceo@x.com", "subject": "urgent!"}) is True
        assert _evaluate_rule(node, {"from": "ceo@x.com", "subject": "later"}) is False

    def test_or_group(self):
        node = {
            "op": "or",
            "rules": [
                {"field": "subject", "operator": "contains", "value": "invoice"},
                {"field": "from", "operator": "contains", "value": "billing"},
            ],
        }
        assert _evaluate_rule(node, {"subject": "stuff", "from": "billing@x.com"}) is True
        assert _evaluate_rule(node, {"subject": "stuff", "from": "no@x.com"}) is False


class TestPreviewFilter:
    def _filter(self, rules, **overrides):
        f = {
            "name": "Test",
            "enabled": True,
            "actions": [{"method": "fileinto", "arguments": {"folders": ["INBOX"]}}],
            "rules": rules,
        }
        f.update(overrides)
        return f

    def test_matches_all_leaves(self):
        f = self._filter({"op": "and", "rules": [{"field": "from", "operator": "contains", "value": "ceo"}]})
        matched, action = preview_filter(f, {"from": "ceo@example.com"})
        assert matched is True
        assert action["method"] == "fileinto"

    def test_no_match(self):
        f = self._filter({"op": "and", "rules": [{"field": "from", "operator": "contains", "value": "ceo"}]})
        matched, action = preview_filter(f, {"from": "other@example.com"})
        assert matched is False
        assert action is not None

    def test_disabled_filter_never_matches(self):
        f = self._filter({"op": "and", "rules": [{"field": "from", "operator": "contains", "value": "ceo"}]}, enabled=False)
        matched, action = preview_filter(f, {"from": "ceo@example.com"})
        assert matched is False
        assert action is None

    def test_empty_rules_no_match(self):
        f = self._filter({"op": "and", "rules": []})
        matched, action = preview_filter(f, {"from": "ceo@example.com"})
        assert matched is False
        assert action is None

    def test_multiple_rules_anded(self):
        f = self._filter({
            "op": "or",
            "rules": [
                {"field": "from", "operator": "contains", "value": "ceo"},
                {"field": "subject", "operator": "contains", "value": "urgent"},
            ],
        })
        # All leaves must hold (ceo AND urgent for full match) because leaves are ANDed
        matched, _ = preview_filter(f, {"from": "ceo@x.com", "subject": "urgent"})
        assert matched is True
        matched, _ = preview_filter(f, {"from": "ceo@x.com", "subject": "later"})
        assert matched is False

    def test_no_actions(self):
        f = self._filter({"op": "and", "rules": [{"field": "from", "operator": "contains", "value": "ceo"}]}, actions=[])
        matched, action = preview_filter(f, {"from": "ceo@example.com"})
        assert matched is True
        assert action is None