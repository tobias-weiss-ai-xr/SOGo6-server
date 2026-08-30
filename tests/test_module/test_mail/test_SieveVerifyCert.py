"""
Unit tests for SOGO_D_SIEVE_VERIFY_CERT — the sieve TLS certificate
verification toggle (added to make sieve filtering work against internal
self-signed ManageSieve servers such as Stalwart, whose listener refuses
plaintext with `NO (ENCRYPT-NEEDED)` but presents a self-signed STARTTLS
certificate everywhere else).
"""
from app.manager.mail.ClientSieve import ClientSieve, _SieveTlsClient
from app.config.settings.DomainSettings import MailSettingsObj


def test_sieve_verify_cert_defaults_to_true():
    obj = MailSettingsObj()
    assert obj.SOGO_D_SIEVE_VERIFY_CERT is True
    args = obj.get_mail_filtering_settings_for_type("sieve")
    assert args["verify_cert"] is True


def test_sieve_verify_cert_can_be_disabled_in_args():
    obj = MailSettingsObj({"SOGO_D_SIEVE_VERIFY_CERT": False})
    args = obj.get_mail_filtering_settings_for_type("sieve")
    assert args["verify_cert"] is False
    # Other sieve args are untouched.
    assert args["port"] == 4190
    assert "server" in args


def test_sieve_verify_cert_encryption_default_still_none():
    """The toggle is independent of the encryption choice (StartTLS keeps it usable)."""
    obj = MailSettingsObj({"SOGO_D_SIEVE_ENCRYPTION": "StartTLS", "SOGO_D_SIEVE_VERIFY_CERT": False})
    args = obj.get_mail_filtering_settings_for_type("sieve")
    assert args["encryption"] == "StartTLS"
    assert args["verify_cert"] is False


def test_client_sieve_exposes_verify_cert():
    client = ClientSieve("sieve.example.org", 4190, "StartTLS", "plain", verify_cert=False)
    assert client.verify_cert is False
    client2 = ClientSieve("sieve.example.org", 4190, "StartTLS", "plain")
    assert client2.verify_cert is True


def test_tls_client_passes_verify_cert_to_sievelib_subclass():
    conn = _SieveTlsClient("sieve.example.org", 4190, verify_cert=False)
    assert conn._verify_cert is False
    conn2 = _SieveTlsClient("sieve.example.org", 4190)
    assert conn2._verify_cert is True
