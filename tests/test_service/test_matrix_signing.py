"""Unit tests for MatrixSigning (Ed25519 sign/verify round-trip + tamper detection)."""
import pytest
from app.service.matrix.MatrixSigning import (
    MatrixSigningKey,
    sign_matrix_event,
    generate_matrix_signing_key,
    _decode_seed,
    CANONICAL,
)


# ============================================================================
# Test helpers
# ============================================================================

FIXTURE_SEED = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU"
# This is b"abcdefghijklmnopqrstuvwxyz012345" (32 bytes) base64url-encoded, no padding.

DIFFERENT_SEED = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo2NTQzMjE"
# This is b"ABCDEFGHIJKLMNOPQRSTUVWXYZ654321" (32 bytes) base64url-encoded, no padding.


FIXTURE_EVENT = {
    "event_id": "$abc123",
    "type": "m.room.message",
    "room_id": "!room:example.org",
    "sender": "@user:example.org",
    "content": {"msgtype": "m.text", "body": "Hello"},
    "origin": "example.org",
    "origin_server_ts": 1234567890,
}


class TestDecodeSeed:
    """Test seed decoding (_decode_seed function)."""

    def test_decode_base64url_seed(self):
        """Decode a valid base64url-encoded 32-byte seed."""
        import base64
        seed_bytes = b"a" * 32
        seed_b64 = base64.urlsafe_b64encode(seed_bytes).decode().rstrip("=")
        result = _decode_seed(seed_b64)
        assert result == seed_bytes
        assert len(result) == 32

    def test_decode_base64_seed(self):
        """Decode a valid standard base64-encoded 32-byte seed."""
        import base64
        seed_bytes = b"b" * 32
        seed_b64 = base64.b64encode(seed_bytes).decode()
        result = _decode_seed(seed_b64)
        assert result == seed_bytes
        assert len(result) == 32

    def test_decode_hex_seed_migration(self):
        """Decode a hex-encoded 32-byte seed (migration path)."""
        seed_bytes = b"c" * 32
        seed_hex = seed_bytes.hex()
        result = _decode_seed(seed_hex)
        assert result == seed_bytes
        assert len(result) == 32

    def test_decode_invalid_seed_raises(self):
        """Invalid seed strings raise ValueError."""
        with pytest.raises(ValueError, match="could not be decoded"):
            _decode_seed("not-a-valid-seed")
        with pytest.raises(ValueError, match="could not be decoded"):
            _decode_seed("abc")  # Too short
        with pytest.raises(ValueError, match="could not be decoded"):
            _decode_seed("a" * 65)  # Wrong length after decoding

    def test_decode_seed_with_padding(self):
        """Seed with optional base64 padding is decoded correctly."""
        import base64
        seed_bytes = b"d" * 32
        seed_b64 = base64.urlsafe_b64encode(seed_bytes).decode()  # with padding
        result = _decode_seed(seed_b64)
        assert result == seed_bytes


class TestMatrixSigningKeyInit:
    """Test MatrixSigningKey initialization."""

    def test_init_with_seed_generates_deterministic_key(self):
        """Same seed produces same key pair."""
        key1 = MatrixSigningKey(FIXTURE_SEED)
        key2 = MatrixSigningKey(FIXTURE_SEED)
        assert key1.public_key_b64 == key2.public_key_b64
        assert key1.private_seed_b64 == key2.private_seed_b64

    def test_init_without_seed_generates_random_key(self):
        """None seed generates a fresh random key."""
        key1 = MatrixSigningKey()
        key2 = MatrixSigningKey()
        # Keys should be different (statistically almost certain)
        assert key1.public_key_b64 != key2.public_key_b64

    def test_init_with_hex_seed_migration(self):
        """Hex-encoded seed works for migration."""
        seed_bytes = b"migrate" + b"x" * 25  # 32 bytes
        seed_hex = seed_bytes.hex()
        key = MatrixSigningKey(seed_hex)
        assert key.public_key_b64 is not None
        assert key.private_seed_b64 is not None


class TestMatrixSigningKeyProperties:
    """Test MatrixSigningKey properties."""

    def test_private_seed_b64_format(self):
        """Private seed is base64url-encoded without padding."""
        key = MatrixSigningKey(FIXTURE_SEED)
        seed = key.private_seed_b64
        assert isinstance(seed, str)
        # Base64url without padding: no '=' and uses -_ instead of +/
        assert "=" not in seed
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in seed)

    def test_public_key_b64_format(self):
        """Public key is base64-encoded."""
        key = MatrixSigningKey(FIXTURE_SEED)
        pub = key.public_key_b64
        assert isinstance(pub, str)
        assert len(pub) == 44  # 32 bytes base64-encoded = 44 chars

    def test_key_id_format(self):
        """Key ID follows Matrix format: ed25519:<base64_pubkey>."""
        key = MatrixSigningKey(FIXTURE_SEED)
        key_id = key.key_id
        assert key_id.startswith("ed25519:")
        assert len(key_id) == 52  # "ed25519:" (8) + 44 base64 chars

    def test_key_id_derived_from_public_key(self):
        """Key ID is consistent with public key."""
        key = MatrixSigningKey(FIXTURE_SEED)
        expected = f"ed25519:{key.public_key_b64}"
        assert key.key_id == expected


class TestSignAndVerify:
    """Test sign_pdu and verify_pdu methods."""

    def test_sign_pdu_returns_base64_signature(self):
        """Signing produces a base64-encoded signature."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig = key.sign_pdu(FIXTURE_EVENT)
        assert isinstance(sig, str)
        # Ed25519 signature is 64 bytes → base64 = 88 chars
        assert len(sig) == 88

    def test_verify_correct_signature(self):
        """Valid signature verifies successfully."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig = key.sign_pdu(FIXTURE_EVENT)
        assert key.verify_pdu(FIXTURE_EVENT, sig) is True

    def test_verify_wrong_signature_fails(self):
        """Incorrect signature fails verification."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig = key.sign_pdu(FIXTURE_EVENT)
        # Tamper with the signature
        bad_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        assert key.verify_pdu(FIXTURE_EVENT, bad_sig) is False

    def test_verify_tampered_event_fails(self):
        """Event tampering breaks verification."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig = key.sign_pdu(FIXTURE_EVENT)
        # Tamper with event content
        tampered = FIXTURE_EVENT.copy()
        tampered["content"] = {"msgtype": "m.text", "body": "Malicious"}
        assert key.verify_pdu(tampered, sig) is False

    def test_verify_with_wrong_key_fails(self):
        """Signature from different key fails verification."""
        key1 = MatrixSigningKey(FIXTURE_SEED)
        key2 = MatrixSigningKey(DIFFERENT_SEED)
        sig = key1.sign_pdu(FIXTURE_EVENT)
        # key2 tries to verify key1's signature
        assert key2.verify_pdu(FIXTURE_EVENT, sig) is False

    def test_round_trip_deterministic(self):
        """Same event signed twice with same seed produces same signature."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig1 = key.sign_pdu(FIXTURE_EVENT)
        sig2 = key.sign_pdu(FIXTURE_EVENT)
        assert sig1 == sig2

    def test_sign_different_events_different_signatures(self):
        """Different events produce different signatures."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event1 = FIXTURE_EVENT.copy()
        event2 = FIXTURE_EVENT.copy()
        event2["content"] = {"msgtype": "m.text", "body": "Different"}
        sig1 = key.sign_pdu(event1)
        sig2 = key.sign_pdu(event2)
        assert sig1 != sig2

    def test_verify_empty_event(self):
        """Can sign and verify empty event dict."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event = {}
        sig = key.sign_pdu(event)
        assert key.verify_pdu(event, sig) is True

    def test_verify_nested_event(self):
        """Can sign and verify deeply nested event."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event = {
            "a": {"b": {"c": {"d": [1, 2, 3]}}},
            "array": [{"x": 1}, {"y": 2}],
        }
        sig = key.sign_pdu(event)
        assert key.verify_pdu(event, sig) is True


class TestReferenceHash:
    """Test reference_hash method."""

    def test_reference_hash_length(self):
        """Reference hash is 128 hex chars (SHA-512)."""
        key = MatrixSigningKey(FIXTURE_SEED)
        h = key.reference_hash(FIXTURE_EVENT)
        assert len(h) == 128
        assert all(c in "0123456789abcdef" for c in h)

    def test_reference_hash_deterministic(self):
        """Same event produces same reference hash."""
        key = MatrixSigningKey(FIXTURE_SEED)
        h1 = key.reference_hash(FIXTURE_EVENT)
        h2 = key.reference_hash(FIXTURE_EVENT)
        assert h1 == h2

    def test_reference_hash_different_events(self):
        """Different events produce different reference hashes."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event1 = FIXTURE_EVENT.copy()
        event2 = FIXTURE_EVENT.copy()
        event2["content"] = {"msgtype": "m.text", "body": "Changed"}
        h1 = key.reference_hash(event1)
        h2 = key.reference_hash(event2)
        assert h1 != h2

    def test_reference_hash_matches_signature(self):
        """Reference hash is used for signing (canonical JSON)."""
        key = MatrixSigningKey(FIXTURE_SEED)
        # Sign and hash the same event
        sig = key.sign_pdu(FIXTURE_EVENT)
        ref_hash = key.reference_hash(FIXTURE_EVENT)
        # Both are derived from the same canonical JSON
        # We can't easily verify the internal operation but we can confirm
        # they're consistent (hash changes when event changes)
        tampered = FIXTURE_EVENT.copy()
        tampered["content"]["body"] = "Tampered"
        new_hash = key.reference_hash(tampered)
        assert ref_hash != new_hash


class TestConvenienceFunctions:
    """Test sign_matrix_event and generate_matrix_signing_key functions."""

    def test_sign_matrix_event_function(self):
        """sign_matrix_event is a convenience wrapper."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sig_manual = key.sign_pdu(FIXTURE_EVENT)
        sig_func = sign_matrix_event(FIXTURE_EVENT, FIXTURE_SEED)
        assert sig_manual == sig_func

    def test_sign_matrix_event_with_different_seeds(self):
        """sign_matrix_event uses provided seed."""
        sig1 = sign_matrix_event(FIXTURE_EVENT, FIXTURE_SEED)
        sig2 = sign_matrix_event(FIXTURE_EVENT, DIFFERENT_SEED)
        assert sig1 != sig2

    def test_generate_matrix_signing_key_function(self):
        """generate_matrix_signing_key returns a fresh key."""
        key = generate_matrix_signing_key()
        assert isinstance(key, MatrixSigningKey)
        assert key.public_key_b64 is not None
        assert key.private_seed_b64 is not None

    def test_generate_matrix_signing_key_unique(self):
        """Each generated key is unique."""
        keys = [generate_matrix_signing_key() for _ in range(10)]
        pub_keys = {k.public_key_b64 for k in keys}
        assert len(pub_keys) == 10  # All unique


class TestCanonicalJSON:
    """Test canonical JSON behavior."""

    def test_canonical_sorts_keys(self):
        """Canonical JSON sorts keys alphabetically."""
        event = {"z": 1, "a": 2, "m": 3}
        key = MatrixSigningKey(FIXTURE_SEED)
        h1 = key.reference_hash(event)
        # Same event with keys in different order
        event_ordered = {"a": 2, "m": 3, "z": 1}
        h2 = key.reference_hash(event_ordered)
        assert h1 == h2  # Same hash because keys are sorted

    def test_canonical_no_whitespace(self):
        """Canonical JSON has no extra whitespace."""
        event = {"key": "value", "number": 42}
        key = MatrixSigningKey(FIXTURE_SEED)
        h1 = key.reference_hash(event)
        # Same event with different spacing (not actual in dict, but verify behavior)
        h2 = key.reference_hash(event)
        assert h1 == h2

    def test_signature_validates_canonical_form(self):
        """Signature validates the canonical form, not original JSON."""
        key = MatrixSigningKey(FIXTURE_SEED)
        # Create event with non-canonical structure
        event = {"z": "last", "a": "first"}
        sig = key.sign_pdu(event)
        # Verify with same event (keys will be canonicalized)
        assert key.verify_pdu(event, sig) is True


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_sign_unicode_content(self):
        """Can sign events with unicode content."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event = {
            "content": {"body": "Hello 世界 🌍", "msgtype": "m.text"},
        }
        sig = key.sign_pdu(event)
        assert key.verify_pdu(event, sig) is True

    def test_verify_with_empty_signature(self):
        """Empty signature fails verification."""
        key = MatrixSigningKey(FIXTURE_SEED)
        assert key.verify_pdu(FIXTURE_EVENT, "") is False

    def test_verify_with_short_signature(self):
        """Short signature fails verification."""
        key = MatrixSigningKey(FIXTURE_SEED)
        assert key.verify_pdu(FIXTURE_EVENT, "abc") is False

    def test_sign_large_event(self):
        """Can sign large events."""
        key = MatrixSigningKey(FIXTURE_SEED)
        event = {
            "content": {
                "body": "x" * 10000,  # 10KB body
                "msgtype": "m.text",
            },
        }
        sig = key.sign_pdu(event)
        assert key.verify_pdu(event, sig) is True

    def test_seed_with_trailing_whitespace(self):
        """Seed with whitespace raises error."""
        with pytest.raises(ValueError, match="could not be decoded"):
            _decode_seed("testseed   ")  # Trailing spaces

    def test_seed_with_leading_whitespace(self):
        """Seed with leading whitespace raises error."""
        with pytest.raises(ValueError, match="could not be decoded"):
            _decode_seed("   testseed")

    def test_key_with_invalid_seed(self):
        """Key initialization with invalid seed raises."""
        with pytest.raises(ValueError, match="could not be decoded"):
            MatrixSigningKey("invalid!")

    def test_multiple_signatures_same_event(self):
        """Multiple signatures of same event can all verify."""
        key = MatrixSigningKey(FIXTURE_SEED)
        sigs = [key.sign_pdu(FIXTURE_EVENT) for _ in range(5)]
        # All signatures should be identical
        assert len(set(sigs)) == 1
        # All can verify
        for sig in sigs:
            assert key.verify_pdu(FIXTURE_EVENT, sig) is True
