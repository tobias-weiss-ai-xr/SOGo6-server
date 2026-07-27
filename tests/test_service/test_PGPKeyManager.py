"""Real integration tests for PGPKeyManager using real Redis."""
import pytest
from app.svc.pgp.PGPKeyManager import PGPKeyManager
from app.svc.pgp.PGPKeyManager import _armor, _dearmor


@pytest.fixture
def manager(real_cache):
    return PGPKeyManager(cache=real_cache)


class TestPGPKeyGeneration:
    def test_generate_keypair_returns_keys(self, manager):
        result = manager.generate_keypair("test@example.org")
        assert "fingerprint" in result
        assert len(result["fingerprint"]) == 40  # SHA-256 hex
        assert result["public_key"].startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
        assert result["private_key"].startswith("-----BEGIN PGP PRIVATE KEY BLOCK-----")

    def test_generate_keypair_different_users(self, manager):
        k1 = manager.generate_keypair("user1@example.org")
        k2 = manager.generate_keypair("user2@example.org")
        assert k1["fingerprint"] != k2["fingerprint"]

    def test_has_keypair_true_after_generation(self, manager):
        manager.generate_keypair("has@example.org")
        assert manager.has_keypair("has@example.org") is True

    def test_has_keypair_false_before_generation(self, manager):
        assert manager.has_keypair("nonexistent@example.org") is False

    def test_get_public_key_returns_armored_key(self, manager):
        manager.generate_keypair("getpub@example.org")
        pub = manager.get_public_key("getpub@example.org")
        assert pub is not None
        assert "PGP PUBLIC KEY BLOCK" in pub

    def test_get_private_key_returns_armored_key(self, manager):
        manager.generate_keypair("getpriv@example.org")
        priv = manager.get_private_key("getpriv@example.org")
        assert priv is not None
        assert "PGP PRIVATE KEY BLOCK" in priv

    def test_delete_keypair_removes_keys(self, manager):
        manager.generate_keypair("delete@example.org")
        assert manager.has_keypair("delete@example.org") is True
        manager.delete_keypair("delete@example.org")
        assert manager.has_keypair("delete@example.org") is False


class TestPGPEncryptDecrypt:
    def test_encrypt_decrypt_roundtrip(self, manager):
        manager.generate_keypair("alice@example.org")
        pub = manager.get_public_key("alice@example.org")
        original = "Hello, this is a secret message!"
        encrypted = manager.encrypt_message(original, pub)
        assert encrypted.startswith("-----BEGIN PGP MESSAGE-----")
        
        priv = manager.get_private_key("alice@example.org")
        decrypted = manager.decrypt_message(encrypted, priv)
        assert decrypted == original

    def test_encrypt_with_passphrase(self, manager):
        manager.generate_keypair("bob@example.org", passphrase="strongpass")
        pub = manager.get_public_key("bob@example.org")
        msg = "Secret with passphrase"
        encrypted = manager.encrypt_message(msg, pub)
        priv = manager.get_private_key("bob@example.org")
        decrypted = manager.decrypt_message(encrypted, priv, passphrase="strongpass")
        assert decrypted == msg

    def test_encrypt_decrypt_multiple_messages(self, manager):
        manager.generate_keypair("multi@example.org")
        pub = manager.get_public_key("multi@example.org")
        priv = manager.get_private_key("multi@example.org")
        messages = ["Short", "A longer message with more content.", "Message with num8ers and spec!@l chars", ""]
        for msg in messages:
            encrypted = manager.encrypt_message(msg, pub)
            decrypted = manager.decrypt_message(encrypted, priv)
            assert decrypted == msg

    def test_decrypt_wrong_key_fails(self, manager):
        manager.generate_keypair("alice@example.org")
        manager.generate_keypair("eve@example.org")
        msg = "Secret message"
        pub_alice = manager.get_public_key("alice@example.org")
        encrypted = manager.encrypt_message(msg, pub_alice)
        priv_eve = manager.get_private_key("eve@example.org")
        with pytest.raises((ValueError, Exception)):
            manager.decrypt_message(encrypted, priv_eve)

    def test_decrypt_invalid_armor_raises(self, manager):
        manager.generate_keypair("test@example.org")
        priv = manager.get_private_key("test@example.org")
        with pytest.raises(ValueError, match="Invalid message armor"):
            manager.decrypt_message("not-a-valid-message", priv)


class TestPGPArmor:
    def test_armor_dearmor_roundtrip(self):
        data = b"hello world binary \x00\x01\x02"
        for label in ["MESSAGE", "PUBLIC KEY BLOCK", "PRIVATE KEY BLOCK"]:
            armored = _armor(data, label)
            assert armored.startswith(f"-----BEGIN PGP {label}-----")
            assert armored.endswith(f"-----END PGP {label}-----\n")
            dearmored = _dearmor(armored)
            assert dearmored == data

    def test_dearmor_invalid_returns_none(self):
        assert _dearmor("no markers here") is None
        assert _dearmor("-----BEGIN PGP X-----\ncontent\n-----END PGP Y-----") is None
        assert _dearmor("") is None


class TestPGPKeyStorage:
    def test_keys_survive_multiple_operations(self, manager):
        manager.generate_keypair("persist@example.org")
        pub1 = manager.get_public_key("persist@example.org")
        manager.get_private_key("persist@example.org")
        pub2 = manager.get_public_key("persist@example.org")
        assert pub1 == pub2

    def test_re_generate_overwrites(self, manager):
        k1 = manager.generate_keypair("overwrite@example.org")
        k2 = manager.generate_keypair("overwrite@example.org")
        assert k1["fingerprint"] != k2["fingerprint"]

    def test_multiple_users_independent(self, manager):
        manager.generate_keypair("a@example.org")
        manager.generate_keypair("b@example.org")
        assert manager.has_keypair("a@example.org") is True
        assert manager.has_keypair("b@example.org") is True
        manager.delete_keypair("a@example.org")
        assert manager.has_keypair("a@example.org") is False
        assert manager.has_keypair("b@example.org") is True
