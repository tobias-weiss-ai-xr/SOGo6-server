"""Unit tests for DnsWizard (SPF/DKIM/DMARC record generation + validation).

Pure static-method module — no DB, no network, no mocks needed.
"""
import pytest
from app.module.admin.DnsWizard import DnsWizard


class TestGenerateSpfRecord:
    def test_basic_record(self):
        rec = DnsWizard.generate_spf_record("example.org")
        assert rec["name"] == "example.org"
        assert rec["type"] == "TXT"
        assert rec["ttl"] == 3600
        assert rec["value"].startswith("v=spf1")
        assert "mx" in rec["value"]
        assert rec["value"].endswith("~all")

    def test_default_mx_added(self):
        rec = DnsWizard.generate_spf_record("example.org")
        assert " mx " in f" {rec['value']} " or rec["value"].endswith(" mx ~all")

    def test_includes_ip4(self):
        rec = DnsWizard.generate_spf_record("example.org", ip4_addresses=["192.0.2.1", "192.0.2.2"])
        assert "ip4:192.0.2.1" in rec["value"]
        assert "ip4:192.0.2.2" in rec["value"]

    def test_includes_ip6(self):
        rec = DnsWizard.generate_spf_record("example.org", ip6_addresses=["2001:db8::1"])
        assert "ip6:2001:db8::1" in rec["value"]

    def test_includes_domains(self):
        rec = DnsWizard.generate_spf_record("example.org", include_domains=["spf.mailer.com"])
        assert "include:spf.mailer.com" in rec["value"]

    def test_policy_overrides(self):
        rec = DnsWizard.generate_spf_record("example.org", policy="-all")
        assert rec["value"].endswith("-all")

    def test_description_contains_domain(self):
        rec = DnsWizard.generate_spf_record("example.org")
        assert "example.org" in rec["description"]
        assert rec["description"].startswith("SPF record")


class TestGenerateDkimRecord:
    def test_basic_record(self):
        rec = DnsWizard.generate_dkim_record("example.org")
        assert rec["name"] == "sogo._domainkey.example.org"
        assert rec["type"] == "TXT"
        assert rec["ttl"] == 3600
        assert rec["selector"] == "sogo"

    def test_with_public_key(self):
        rec = DnsWizard.generate_dkim_record("example.org", public_key="AABBCC==")
        assert "v=DKIM1" in rec["value"]
        assert "p=AABBCC==" in rec["value"]

    def test_placeholder_when_no_key(self):
        rec = DnsWizard.generate_dkim_record("example.org")
        assert "REPLACE_WITH_PUBLIC_KEY" in rec["value"]
        assert "openssl genpkey" in rec["value"]

    def test_custom_selector_and_key_type(self):
        rec = DnsWizard.generate_dkim_record(
            "example.org", selector="k1", key_type="rsa", public_key="KEY"
        )
        assert rec["name"] == "k1._domainkey.example.org"
        assert "k=rsa" in rec["value"]

    def test_ed25519_key_type(self):
        rec = DnsWizard.generate_dkim_record("example.org", key_type="ed25519")
        assert "k=ed25519" in rec["value"]


class TestGenerateDmarcRecord:
    def test_basic_record(self):
        rec = DnsWizard.generate_dmarc_record("example.org")
        assert rec["name"] == "_dmarc.example.org"
        assert rec["type"] == "TXT"
        assert rec["value"].startswith("v=DMARC1")
        assert "p=none" in rec["value"]
        assert "pct=100" in rec["value"]

    def test_policy(self):
        rec = DnsWizard.generate_dmarc_record("example.org", policy="reject")
        assert "p=reject" in rec["value"]

    def test_rua_and_ruf(self):
        rec = DnsWizard.generate_dmarc_record(
            "example.org", rua_email="dmarc@example.org", ruf_email="fr@example.org"
        )
        assert "rua=mailto:dmarc@example.org" in rec["value"]
        assert "ruf=mailto:fr@example.org" in rec["value"]

    def test_subdomain_policy(self):
        rec = DnsWizard.generate_dmarc_record("example.org", subdomain_policy="quarantine")
        assert "sp=quarantine" in rec["value"]

    def test_custom_pct_and_alignment(self):
        rec = DnsWizard.generate_dmarc_record("example.org", pct=50, aspf="s", adkim="s")
        assert "pct=50" in rec["value"]
        assert "aspf=s" in rec["value"]
        assert "adkim=s" in rec["value"]

    def test_description(self):
        rec = DnsWizard.generate_dmarc_record("example.org")
        assert "DMARC record for example.org" in rec["description"]


class TestValidateSpf:
    @pytest.mark.parametrize(
        "value,valid",
        [
            ("v=spf1 mx ~all", True),
            ("v=spf1 mx -all", True),
            ("v=spf1 ip4:192.0.2.1 include:_spf.google.com ~all", True),
        ],
    )
    def test_valid_values(self, value, valid):
        res = DnsWizard.validate_spf(value)
        assert res["valid"] is valid
        assert res["errors"] == []

    def test_missing_vspf1(self):
        res = DnsWizard.validate_spf("mx ~all")
        assert res["valid"] is False
        assert any("v=spf1" in e for e in res["errors"])

    def test_too_short(self):
        res = DnsWizard.validate_spf("v=spf1")
        assert res["valid"] is False
        assert any("too short" in e for e in res["errors"])

    def test_missing_catch_all(self):
        res = DnsWizard.validate_spf("v=spf1 mx ip4:1.2.3.4")
        assert res["valid"] is False
        assert any("catch-all" in e for e in res["errors"])

    def test_too_many_lookups_is_error(self):
        mechanisms = " ".join([f"ip4:192.0.2.{i}" for i in range(11)])
        spf = f"v=spf1 {mechanisms} ~all"
        res = DnsWizard.validate_spf(spf)
        # ip4 doesn't count toward DNS lookups; use include
        spf_include = "v=spf1 " + " ".join(["include:_s%d.example.com" % i for i in range(11)]) + " ~all"
        res = DnsWizard.validate_spf(spf_include)
        assert res["valid"] is False
        assert any("DNS lookups" in e for e in res["errors"])

    def test_lookups_approaching_limit_warns(self):
        spf = "v=spf1 " + " ".join(["include:_s%d.example.com" % i for i in range(9)]) + " ~all"
        res = DnsWizard.validate_spf(spf)
        assert res["valid"] is True
        assert any("approaching limit" in w for w in res["warnings"])

    def test_ptr_warns(self):
        res = DnsWizard.validate_spf("v=spf1 ptr ~all")
        assert any("ptr" in w for w in res["warnings"])

    def test_valid_returns_structured(self):
        res = DnsWizard.validate_spf("v=spf1 mx ~all")
        assert set(res.keys()) == {"valid", "warnings", "errors"}


class TestValidateDmarc:
    def test_valid_record(self):
        res = DnsWizard.validate_dmarc(
            'v=DMARC1; p=none; pct=100; rua=mailto:dmarc@example.org'
        )
        assert res["valid"] is True

    def test_missing_vdmarc1(self):
        res = DnsWizard.validate_dmarc("p=none")
        assert res["valid"] is False
        assert any("v=DMARC1" in e for e in res["errors"])

    def test_invalid_policy(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=bogus")
        assert res["valid"] is False
        assert any("policy" in e for e in res["errors"])

    def test_policy_none_warns(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=none")
        assert any("monitoring only" in w for w in res["warnings"])

    def test_invalid_pct_out_of_range(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=none; pct=150")
        assert res["valid"] is False
        assert any("pct" in e for e in res["errors"])

    def test_invalid_pct_non_numeric(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=none; pct=abc")
        assert res["valid"] is False
        assert any("pct" in e for e in res["errors"])

    def test_invalid_pct_low(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=none; pct=0")
        assert res["valid"] is False
        assert any("pct" in e for e in res["errors"])

    def test_returns_structured(self):
        res = DnsWizard.validate_dmarc("v=DMARC1; p=none")
        assert set(res.keys()) == {"valid", "warnings", "errors"}
