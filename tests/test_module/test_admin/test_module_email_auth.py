"""Unit tests for the Email Authentication (DKIM/DMARC/SPF) module logic.

Fixture-free by design — the module is a pure in-memory engine, no DB, no
client/auth fixtures required.
"""
import pytest

from app.module.admin.ModuleEmailAuth import ModuleEmailAuth


class TestDomainRegistry:
    def test_add_and_get_domain(self):
        module = ModuleEmailAuth()
        domain = module.add_domain("Example.ORG", "Primary")
        assert domain["name"] == "example.org"  # lowercased
        assert module.get_domain("example.org")["description"] == "Primary"

    def test_duplicate_domain_raises_keyerror(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        with pytest.raises(KeyError):
            module.add_domain("EXAMPLE.org")

    def test_remove_domain_cleans_configs(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.set_dkim("example.org", {})
        module.set_dmarc("example.org", {})
        module.set_spf("example.org", {})
        assert module.remove_domain("example.org") is True
        assert module.get_dkim("example.org") is None
        assert module.get_dmarc("example.org") is None
        assert module.get_spf("example.org") is None
        assert module.remove_domain("example.org") is False

    def test_list_domains_returns_copies(self):
        module = ModuleEmailAuth()
        module.add_domain("a.example")
        module.add_domain("b.example")
        domains = module.list_domains()
        assert len(domains) == 2
        domains[0]["name"] = "mutated"
        assert module.get_domain("a.example") is not None


class TestDkim:
    def test_generate_key_pair_rsa2048(self):
        module = ModuleEmailAuth()
        keys = module.generate_key_pair(2048)
        assert keys["private_key"].startswith("-----BEGIN PRIVATE KEY-----")
        assert len(keys["public_key"]) > 100
        assert keys["key_type"] == "rsa"
        assert len(keys["public_key_fingerprint"]) == 16

    @pytest.mark.parametrize("length", [1024, 2048, 4096])
    def test_generate_key_pair_supported_lengths(self, length):
        keys = ModuleEmailAuth().generate_key_pair(length)
        assert keys["key_length"] == str(length)

    def test_generate_key_pair_invalid_length(self):
        with pytest.raises(ValueError):
            ModuleEmailAuth().generate_key_pair(512)

    def test_generate_dkim_dns_record(self):
        record = ModuleEmailAuth.generate_dkim_dns_record(
            "example.org", "default", "ABCDEF==", "rsa"
        )
        assert record["name"] == "default._domainkey.example.org"
        assert record["type"] == "TXT"
        assert record["value"] == "v=DKIM1; k=rsa; p=ABCDEF=="

    def test_set_get_dkim(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        config = module.set_dkim("example.org", {"selector": "sogo", "public_key": "k"})
        assert config["domain"] == "example.org"
        assert config["selector"] == "sogo"
        assert module.get_dkim("example.org")["public_key"] == "k"

    def test_set_dkim_requires_existing_domain(self):
        module = ModuleEmailAuth()
        with pytest.raises(KeyError):
            module.set_dkim("ghost.org", {})

    def test_rotate_dkim_generates_new_key(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.set_dkim("example.org", {"public_key": "old-key"})
        rotated = module.rotate_dkim("example.org")
        assert rotated["public_key"] != "old-key"
        assert rotated["dns_record"]["name"] == "default._domainkey.example.org"

    def test_validate_dkim_no_config_or_lookup_failure(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        result = module.validate_dkim("example.org")
        # Whether or not dnspython is available, without a configured public
        # key the validation must fail.
        assert result["is_valid"] is False
        assert result["dns_record_found"] is False
        assert any("public key" in e for e in result["errors"])

    def test_validate_dkim_reports_lookup_availability(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        keys = module.generate_key_pair(2048)
        module.set_dkim("example.org", {"public_key": keys["public_key"]})
        result = module.validate_dkim("example.org")
        assert "dns_lookup_available" in result
        assert "checked_at" in result

    def test_update_dkim_partial(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.set_dkim("example.org", {"selector": "a", "notes": "keep"})
        updated = module.update_dkim("example.org", {"selector": "b"})
        assert updated["selector"] == "b"
        assert updated["notes"] == "keep"


class TestDmarc:
    def test_generate_record_defaults(self):
        record = ModuleEmailAuth.generate_dmarc_record({})
        assert record.startswith("v=DMARC1; p=none")
        assert "pct=100" in record
        assert "aspf=r" in record

    def test_generate_record_full(self):
        record = ModuleEmailAuth.generate_dmarc_record({
            "policy": "quarantine",
            "subdomain_policy": "none",
            "pct": 50,
            "rua": ["dmarc@example.org"],
            "ruf": ["forensic@example.org"],
        })
        assert "p=quarantine" in record
        assert "sp=none" in record
        assert "pct=50" in record
        assert "rua=mailto:dmarc@example.org" in record
        assert "ruf=mailto:forensic@example.org" in record

    def test_set_get_dmarc(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        config = module.set_dmarc("example.org", {"policy": "reject"})
        assert config["record_value"].startswith("v=DMARC1; p=reject")
        assert module.get_dmarc("example.org")["policy"] == "reject"

    def test_update_dmarc_regenerates_record(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.set_dmarc("example.org", {"policy": "none"})
        updated = module.update_dmarc("example.org", {"policy": "quarantine"})
        assert "p=quarantine" in updated["record_value"]

    def test_parse_aggregate_report(self):
        xml = """<?xml version="1.0"?>
        <feedback>
          <report_metadata>
            <org_name>Example Inc.</org_name>
            <email>reports@example.com</email>
            <report_id>r1</report_id>
            <date_range><begin>1</begin><end>2</end></date_range>
          </report_metadata>
          <policy_published>
            <domain>example.org</domain><adkim>r</adkim><aspf>r</aspf>
            <p>quarantine</p><sp>none</sp><pct>100</pct>
          </policy_published>
          <record>
            <row>
              <source_ip>192.0.2.1</source_ip><count>5</count>
              <policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf></policy_evaluated>
            </row>
            <identifiers><header_from>example.org</header_from></identifiers>
          </record>
        </feedback>"""
        result = ModuleEmailAuth.parse_aggregate_report(xml)
        assert result["report_metadata"]["org_name"] == "Example Inc."
        assert result["policy_published"]["domain"] == "example.org"
        assert result["records"][0]["source_ip"] == "192.0.2.1"
        assert result["records"][0]["dkim"] == "pass"

    def test_dmarc_reports_store(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.add_dmarc_report("example.org", {"report_id": "x"})
        reports = module.get_dmarc_reports("example.org")
        assert len(reports) == 1
        assert module.get_dmarc_reports("other.org") == []


class TestSpf:
    def test_generate_record_simple(self):
        record = ModuleEmailAuth.generate_spf_record({"all_qualifier": "-all"})
        assert record == "v=spf1 -all"

    def test_generate_record_mechanisms(self):
        record = ModuleEmailAuth.generate_spf_record({
            "include_mechanisms": ["_spf.google.com"],
            "ip4_mechanisms": ["192.0.2.0/24"],
            "mx_mechanisms": [""],
            "all_qualifier": "~all",
        })
        assert record == "v=spf1 include:_spf.google.com ip4:192.0.2.0/24 mx ~all"

    def test_generate_record_raw(self):
        record = ModuleEmailAuth.generate_spf_record({
            "raw_mail_servers": "a mx",
            "all_qualifier": "-all",
        })
        assert record == "v=spf1 a mx -all"

    def test_set_get_spf(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        config = module.set_spf("example.org", {"include_mechanisms": ["_spf.google.com"]})
        assert config["record_value"] == "v=spf1 include:_spf.google.com -all"

    def test_validate_spf_valid(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        module.set_spf("example.org", {"include_mechanisms": ["_spf.google.com"]})
        result = module.validate_spf("example.org")
        assert result["is_valid"] is True
        assert result["dns_lookup_count"] == 1
        assert result["over_lookup_limit"] is False

    def test_validate_spf_missing_all(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        # A raw record without any catch-all mechanism is invalid per RFC 7208.
        module.set_spf("example.org", {"raw_mail_servers": "a mx", "all_qualifier": None})
        result = module.validate_spf("example.org")
        assert result["is_valid"] is False
        assert any("catch-all" in e for e in result["errors"])

    def test_validate_spf_lookup_limit(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        many = [f"inc{i}.example.org" for i in range(12)]
        module.set_spf("example.org", {"include_mechanisms": many})
        result = module.validate_spf("example.org")
        assert result["over_lookup_limit"] is True
        assert result["is_valid"] is False


class TestStatusAndBulk:
    def test_domain_status_none(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        status = module.get_domain_status("example.org")
        assert status["overall_status"] == "none"
        assert status["dkim_status"] == "none"
        assert status["overall_recommendations"]

    def test_domain_status_ok(self):
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        keys = module.generate_key_pair(2048)
        module.set_dkim("example.org", {"public_key": keys["public_key"]})
        module.set_dmarc("example.org", {"policy": "none"})
        module.set_spf("example.org", {})
        status = module.get_domain_status("example.org")
        assert status["dkim_status"] == "ok"
        assert status["dmarc_status"] == "ok"
        assert status["spf_status"] == "ok"
        assert status["overall_status"] == "ok"

    def test_validate_all(self):
        module = ModuleEmailAuth()
        module.add_domain("a.example")
        module.add_domain("b.example")
        assert len(module.validate_all()) == 2

    def test_domain_status_unknown_domain(self):
        module = ModuleEmailAuth()
        with pytest.raises(KeyError):
            module.get_domain_status("ghost.org")

    def test_test_email_auth_never_raises(self):
        result = ModuleEmailAuth.test_email_auth("admin@example.org", smtp_server="127.0.0.1", smtp_port=1)
        assert result["sent"] is False
        assert "smtp_response" in result
        assert result["domain"] == "example.org"
