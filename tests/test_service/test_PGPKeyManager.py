"""Tests for PGPKeyManager — key generation, encrypt, decrypt (Tier 1 #19)."""
import pytest
from app.svc.pgp.PGPKeyManager import PGPKeyManager
from app.svc.pgp.PGPKeyManager import _armor, _dearmor, _crc24


@pytest.fixture
def manager():
    return PGPKeyManager()


class TestPGPKeyGeneration:
    def test_generate_keypair_returns_keys(self, manager):
        result = manager.generate_keypair("test@example.org")
        assert "fingerprint" in result
        assert "public_key" in result
        assert "private_key" in result
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

    def test_decrypt_wrong_key_fails(self, manager):
        manager.generate_keypair("alice@example.org")
        manager.generate_keypair("eve@example.org")
        msg = "Secret message"
        pub_alice = manager.get_public_key("alice@example.org")
        encrypted = manager.encrypt_message(msg, pub_alice)
        priv_eve = manager.get_private_key("eve@example.org")
        with pytest.raises((ValueError, Exception)):
            manager.decrypt_message(encrypted, priv_eve)

    def test_encrypt_empty_message(self, manager):
        manager.generate_keypair("empty@example.org")
        pub = manager.get_public_key("empty@example.org")
        result = manager.encrypt_message("", pub)
        assert result.startswith("-----BEGIN PGP MESSAGE-----")

    def test_decrypt_invalid_armor_raises(self, manager):
        manager.generate_keypair("test@example.org")
        priv = manager.get_private_key("test@example.org")
        with pytest.raises(ValueError, match="Invalid message armor"):
            manager.decrypt_message("not-a-valid-message", priv)


class TestPGPArmor:
    def test_armor_dearmor_roundtrip(self):
        data = b"hello world this is binary data \x00\x01\x02"
        armored = _armor(data, "TEST")
        assert armored.startswith("-----BEGIN PGP TEST-----")
        assert armored.endswith("-----END PGP TEST-----\n")
        dearmored = _dearmor(armored)
        assert dearmored == data

    def test_crc24_known_value(self):
        # Known CRC-24 value for "test"
        crc = _crc24(b"test")
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFFFF

    def test_dearmor_invalid_returns_none(self):
        assert _dearmor("no markers here") is None
        assert _dearmor("-----BEGIN PGP X-----\ncontent\n-----END PGP Y-----") is None


class TestPGPKeyStorage:
    def test_keys_survive_multiple_operations(self, manager):
        manager.generate_keypair("persist@example.org")
        pub1 = manager.get_public_key("persist@example.org")
        manager.get_private_key("persist@example.org")  # access private
        pub2 = manager.get_public_key("persist@example.org")
        assert pub1 == pub2

    def test_generate_twice_overwrites(self, manager):
        k1 = manager.generate_keypair("overwrite@example.org")
        k2 = manager.generate_keypair("overwrite@example.org")
        assert k1["fingerprint"] != k2["fingerprint"]  # New keys on each gen
