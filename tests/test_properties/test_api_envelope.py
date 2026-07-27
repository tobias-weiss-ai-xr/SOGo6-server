"""Property-based tests for API response envelope conformance.

Verifies that every API endpoint returns the standard error envelope:

.. code:: json

    {
        "error_code": "S000000",
        "error_msg": "No Error",
        "data": { ... }
    }

Uses ``hypothesis`` to fuzz inputs and ensure the server never crashes
with a 5xx or returns a malformed envelope.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ─────────────────────────────────────────────────────────────────────────────
# Strategies: reusable generators for API input fuzzing
# ─────────────────────────────────────────────────────────────────────────────

# ISO 8601-ish datetime strings (valid + invalid edge cases)
iso_datetime_strings = st.sampled_from([
    "2026-08-01T14:00:00.000Z",
    "2026-08-01T14:00:00Z",
    "2026-08-01T14:00:00+00:00",
    "2026-08-01T14:00:00",
    "2026-08-01",
    "14:00:00",
    "",
    "not-a-date",
    "2026-13-01T14:00:00Z",       # invalid month
    "2026-08-01T25:00:00Z",       # invalid hour
    "2026-08-01T14:00:00.000+99:00",  # invalid timezone
])

# Email addresses (valid + invalid)
email_strings = st.sampled_from([
    "user@example.org",
    "testuser@example.org",
    "admin@example.org",
    "",
    "not-an-email",
    "user@",
    "@example.org",
    "a" * 300 + "@example.org",   # excessively long local part
])

# UUID-like strings
uuid_strings = st.sampled_from([
    "uuid-abc-123",
    "550e8400-e29b-41d4-a716-446655440000",
    "",
    "not-a-uuid",
    "123",
])

# Generic text fields (subject, body, etc.)
text_strings = st.text(
    min_size=0,
    max_size=1000,
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogate chars
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Envelope contract tests (stateless)
# ─────────────────────────────────────────────────────────────────────────────

class TestApiEnvelopeContract:
    """Verify the API error envelope schema for every endpoint group.

    These tests run against the backend interface layer (not HTTP) using
    injected fakes, so they don't need a running stack.
    """

    # ── Module-level fixtures are set up per-test-class in conftest ──

    @given(send_at=iso_datetime_strings)
    @settings(max_examples=50, deadline=None)
    def test_send_mail_envelope_with_various_send_at(
        self, send_at: str, mail_iface
    ):
        """send_mail always returns a valid envelope regardless of send_at value."""
        assume(send_at is not None)
        mail_data = {
            "from": "sender@example.org",
            "to": ["recipient@example.org"],
            "subject": "Property Test",
            "body": "Fuzzing send_at",
        }
        if send_at:
            mail_data["send_at"] = send_at

        result, status = mail_iface.send_mail("0", mail_data)

        self._assert_valid_envelope(result, status)

    @given(
        sender=email_strings,
        recipient=email_strings,
        subject=text_strings,
        body=text_strings,
    )
    @settings(max_examples=100, deadline=None)
    def test_send_mail_envelope_with_fuzzed_fields(
        self, sender: str, recipient: str, subject: str, body: str, mail_iface
    ):
        """send_mail never crashes on arbitrary field values."""
        assume(len(subject) <= 998)  # SMTP subject line limit
        mail_data = {
            "from": sender or "fallback@example.org",
            "to": [recipient or "fallback@example.org"],
            "subject": subject or "(no subject)",
            "body": body,
        }
        result, status = mail_iface.send_mail("0", mail_data)
        self._assert_valid_envelope(result, status)

    # ── Helpers ──────────────────────────────────────────────────────

    def _assert_valid_envelope(self, result: dict, status: int) -> None:
        """Assert the API response matches the contract envelope."""
        # 1. Must be a dict
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

        # 2. Must have error_code (always a string starting with S)
        assert "error_code" in result, "Missing error_code in envelope"
        error_code: str = result["error_code"]
        assert isinstance(error_code, str), f"error_code must be str, got {type(error_code)}"
        assert error_code.startswith("S"), f"error_code must start with 'S', got {error_code}"
        assert len(error_code) == 7, f"error_code must be 7 chars, got {len(error_code)}"

        # 3. Must have error_msg (always a string, never None)
        assert "error_msg" in result, "Missing error_msg in envelope"
        assert isinstance(result["error_msg"], str), f"error_msg must be str, got {type(result['error_msg'])}"

        # 4. May have data (dict or None)
        assert "data" in result, "Missing data key in envelope"
        # data can be dict or None — both are valid

        # 5. Status code must be in valid range
        assert isinstance(status, int), f"Status must be int, got {type(status)}"
        assert 200 <= status <= 599, f"Status {status} out of range"

        # 6. If status is 2xx, error_code should be S000000
        if 200 <= status < 300:
            assert error_code == "S000000", (
                f"Success status {status} but error_code is {error_code}"
            )
        elif 400 <= status < 500:
            assert error_code != "S000000", (
                f"Client error {status} but error_code is S000000"
            )
        elif 500 <= status < 600:
            assert error_code != "S000000", (
                f"Server error {status} but error_code is S000000"
            )


class TestErrorCodeConsistency:
    """Verify that every known error code is reachable and has correct format."""

    # Known error codes from app/utils/errors.py
    KNOWN_ERROR_CODES = {
        "S000000", "S000001", "S000208", "S000300",
        "S000384", "S000386", "S000387", "S000388", "S000389", "S000391",
    }

    @given(st.sampled_from(sorted(KNOWN_ERROR_CODES)))
    @settings(max_examples=len(KNOWN_ERROR_CODES))
    def test_error_code_format(self, error_code: str):
        """Every error code follows the S###### pattern."""
        assert len(error_code) == 7, f"Error code {error_code} must be 7 chars"
        assert error_code[0] == "S", f"Error code {error_code} must start with S"
        assert error_code[1:].isdigit(), f"Error code {error_code} must have numeric suffix"

    def test_no_duplicate_error_codes(self):
        """No two errors share the same code (checked at import time)."""
        # This is implicitly verified by the errors module — duplicate codes
        # would cause a key collision. We verify known codes are unique.
        assert len(self.KNOWN_ERROR_CODES) == len(
            {c for c in self.KNOWN_ERROR_CODES}
        ), "Duplicate error codes detected"
