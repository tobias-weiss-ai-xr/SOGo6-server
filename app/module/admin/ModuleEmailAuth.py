"""Email authentication (DKIM/DMARC/SPF) business logic.

Pure-logic module used by the admin ``/email-auth`` API blueprint. Contains:

* DKIM RSA key pair generation + DNS TXT record builders
* DMARC policy record builder + aggregate report (XML) parser
* SPF record builder + RFC 7208 syntax/lookup-limit validation
* In-memory per-domain configuration store (domains, dkim, dmarc, spf)

DNS live lookups are best-effort: when ``dnspython`` is installed the
``validate_dkim_dns`` / ``validate_dmarc_dns`` / ``validate_spf_dns``
methods resolve real records; otherwise they return ``dns_lookup_available``
= False and rely on static record validation only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - optional dependency
    import dns.resolver  # type: ignore

    _DNSPYTHON_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DNSPYTHON_AVAILABLE = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModuleEmailAuth:
    """In-memory email authentication configuration store + generators."""

    def __init__(self) -> None:
        self._domains: dict[str, dict[str, Any]] = {}
        self._dkim: dict[str, dict[str, Any]] = {}
        self._dmarc: dict[str, dict[str, Any]] = {}
        self._spf: dict[str, dict[str, Any]] = {}
        self._reports: dict[str, list[dict[str, Any]]] = {}

    # ── Domain registry ──────────────────────────────────────────────────────

    def add_domain(self, name: str, description: str = "", is_active: bool = True) -> dict[str, Any]:
        """Register a domain. Raises KeyError when it already exists."""
        name = name.strip().lower()
        if name in self._domains:
            raise KeyError(name)
        now = _utcnow()
        domain = {
            "name": name,
            "description": description,
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        }
        self._domains[name] = domain
        return dict(domain)

    def list_domains(self) -> list[dict[str, Any]]:
        return [dict(d) for d in self._domains.values()]

    def get_domain(self, name: str) -> dict[str, Any] | None:
        domain = self._domains.get(name.strip().lower())
        return dict(domain) if domain else None

    def remove_domain(self, name: str) -> bool:
        name = name.strip().lower()
        if name not in self._domains:
            return False
        del self._domains[name]
        self._dkim.pop(name, None)
        self._dmarc.pop(name, None)
        self._spf.pop(name, None)
        return True

    def get_domain_status(self, name: str) -> dict[str, Any]:
        """Aggregate authentication status for one domain."""
        domain = self.get_domain(name)
        if not domain:
            raise KeyError(name)
        dkim = self._dkim.get(name)
        dmarc = self._dmarc.get(name)
        spf = self._spf.get(name)

        dkim_status, dkim_msg = self._config_status(dkim, "dkim")
        dmarc_status, dmarc_msg = self._config_status(dmarc, "dmarc")
        spf_status, spf_msg = self._config_status(spf, "spf")

        statuses = [dkim_status, dmarc_status, spf_status]
        if "error" in statuses:
            overall = "error"
        elif "warning" in statuses:
            overall = "warning"
        elif all(s == "ok" for s in statuses):
            overall = "ok"
        else:
            overall = "none"

        recommendations: list[str] = []
        if dkim_status != "ok":
            recommendations.append("Configure DKIM signing (selector + RSA key pair)")
        if dmarc_status != "ok":
            recommendations.append("Publish a DMARC policy (start with p=none)")
        if spf_status != "ok":
            recommendations.append("Publish an SPF record (v=spf1 ... -all)")

        return {
            "domain": name,
            "dkim_status": dkim_status,
            "dkim_status_msg": dkim_msg,
            "dmarc_status": dmarc_status,
            "dmarc_status_msg": dmarc_msg,
            "spf_status": spf_status,
            "spf_status_msg": spf_msg,
            "overall_status": overall,
            "overall_recommendations": recommendations,
        }

    @staticmethod
    def _config_status(config: dict[str, Any] | None, kind: str) -> tuple[str, str]:
        if config is None:
            return "none", f"No {kind.upper()} configuration"
        if config.get("enabled") is False:
            return "none", f"{kind.upper()} disabled for this domain"
        return "ok", f"{kind.upper()} configured"

    def validate_all(self) -> list[dict[str, Any]]:
        """Validate every configured domain."""
        return [self.get_domain_status(name) for name in self._domains]

    # ── DKIM ─────────────────────────────────────────────────────────────────

    def generate_key_pair(self, key_length: int = 2048) -> dict[str, str]:
        """Generate an RSA key pair for DKIM signing."""
        if key_length not in (1024, 2048, 4096):
            raise ValueError(f"Invalid key length: {key_length}")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_length)
        public_key = private_key.public_key()

        public_key_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_key_b64 = base64.b64encode(public_key_der).decode("ascii")

        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

        return {
            "private_key": private_key_pem,
            "public_key": public_key_b64,
            "key_type": "rsa",
            "key_length": str(key_length),
            "public_key_fingerprint": hashlib.sha256(public_key_b64.encode()).hexdigest()[:16],
        }

    @staticmethod
    def generate_dkim_dns_record(domain: str, selector: str, public_key: str, key_type: str = "rsa") -> dict[str, Any]:
        """Build the DKIM DNS TXT record payload."""
        value = f"v=DKIM1; k={key_type}; p={public_key}"
        return {
            "name": f"{selector}._domainkey.{domain}",
            "type": "TXT",
            "value": value,
            "ttl": 3600,
            "selector": selector,
            "description": f"DKIM record for {domain} using selector '{selector}' ({key_type}).",
        }

    def set_dkim(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        """Configure DKIM for a domain (upsert)."""
        domain = domain.strip().lower()
        if domain not in self._domains:
            raise KeyError(domain)
        selector = config.get("selector", "default")
        now = _utcnow()
        dkim: dict[str, Any] = {
            "domain": domain,
            "selector": selector,
            "enabled": config.get("enabled", True),
            "key_length": config.get("key_length", 2048),
            "signing_algorithm": config.get("signing_algorithm", "rsa-sha256"),
            "headers_to_sign": config.get("headers_to_sign"),
            "notes": config.get("notes", ""),
            "public_key": config.get("public_key"),
            "dns_record": config.get("dns_record"),
        }
        existing = self._dkim.get(domain)
        if existing:
            dkim["created_at"] = existing.get("created_at", now)
        else:
            dkim["created_at"] = now
        dkim["updated_at"] = now
        self._dkim[domain] = dkim
        return dict(dkim)

    def get_dkim(self, domain: str) -> dict[str, Any] | None:
        dkim = self._dkim.get(domain.strip().lower())
        return dict(dkim) if dkim else None

    def list_dkim(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._dkim.values()]

    def update_dkim(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        """Update an existing DKIM config (partial merge)."""
        domain = domain.strip().lower()
        existing = self.get_dkim(domain)
        if not existing:
            raise KeyError(domain)
        merged = {**existing, **{k: v for k, v in config.items() if v is not None}}
        merged["updated_at"] = _utcnow()
        self._dkim[domain] = merged
        return dict(merged)

    def remove_dkim(self, domain: str) -> bool:
        return self._dkim.pop(domain.strip().lower(), None) is not None

    def rotate_dkim(self, domain: str, key_length: int | None = None) -> dict[str, Any]:
        """Generate a fresh key pair for an existing DKIM config."""
        domain = domain.strip().lower()
        existing = self.get_dkim(domain)
        if not existing:
            raise KeyError(domain)
        length = key_length or existing.get("key_length", 2048)
        keys = self.generate_key_pair(length)
        existing["key_length"] = length
        existing["public_key"] = keys["public_key"]
        existing["dns_record"] = self.generate_dkim_dns_record(
            domain, existing["selector"], keys["public_key"], existing.get("key_type", "rsa")
        )
        existing["updated_at"] = _utcnow()
        self._dkim[domain] = existing
        return dict(existing)

    def validate_dkim(self, domain: str, selector: str | None = None) -> dict[str, Any]:
        """Validate a DKIM configuration (DNS best-effort, static fallback)."""
        domain = domain.strip().lower()
        config = self.get_dkim(domain)
        sel = selector or (config or {}).get("selector", "default")
        if config is None or not config.get("public_key"):
            return {
                "domain": domain,
                "selector": sel,
                "is_valid": False,
                "dns_record_found": False,
                "record_value": None,
                "expected_value": None,
                "errors": ["No DKIM public key configured for this domain"],
                "warnings": [],
                "dns_lookup_available": _DNSPYTHON_AVAILABLE,
                "checked_at": _utcnow(),
            }
        fqdn = f"{sel}._domainkey.{domain}"
        expected = f"v=DKIM1; k={config.get('key_type', 'rsa')}; p={config['public_key']}"
        if _DNSPYTHON_AVAILABLE:
            try:
                answers = dns.resolver.resolve(fqdn, "TXT")
                record = "".join(
                    b.decode("utf-8", "ignore") if isinstance(b, bytes) else str(b)
                    for answer in answers
                    for b in answer.strings
                )
                return {
                    "domain": domain,
                    "selector": sel,
                    "is_valid": "p=" in record and len(record) > 0,
                    "dns_record_found": True,
                    "record_value": record,
                    "expected_value": expected,
                    "errors": [] if "p=" in record else ["DKIM record found but has no p= tag"],
                    "warnings": [],
                    "dns_lookup_available": True,
                    "checked_at": _utcnow(),
                }
            except Exception as exc:  # noqa: BLE001 - best effort
                return {
                    "domain": domain,
                    "selector": sel,
                    "is_valid": False,
                    "dns_record_found": False,
                    "record_value": None,
                    "expected_value": expected,
                    "errors": [f"DNS lookup failed: {exc}"],
                    "warnings": [],
                    "dns_lookup_available": True,
                    "checked_at": _utcnow(),
                }
        return {
            "domain": domain,
            "selector": sel,
            "is_valid": False,
            "dns_record_found": False,
            "record_value": None,
            "expected_value": expected,
            "errors": ["dnspython not installed — live DNS validation unavailable"],
            "warnings": [],
            "dns_lookup_available": False,
            "checked_at": _utcnow(),
        }

    # ── DMARC ────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_dmarc_record(config: dict[str, Any]) -> str:
        """Build the DMARC DNS TXT value from a policy config."""
        tags = ["v=DMARC1", f"p={config.get('policy', 'none')}"]
        if config.get("subdomain_policy"):
            tags.append(f"sp={config['subdomain_policy']}")
        tags.append(f"pct={config.get('pct', 100)}")
        tags.append(f"aspf={config.get('aspf', 'r')}")
        tags.append(f"adkim={config.get('adkim', 'r')}")
        for addr in config.get("rua") or []:
            tags.append(f"rua=mailto:{addr}")
        for addr in config.get("ruf") or []:
            tags.append(f"ruf=mailto:{addr}")
        if config.get("ri"):
            tags.append(f"ri={config['ri']}")
        return "; ".join(tags)

    def set_dmarc(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        domain = domain.strip().lower()
        if domain not in self._domains:
            raise KeyError(domain)
        now = _utcnow()
        dmarc: dict[str, Any] = {
            "domain": domain,
            "enabled": config.get("enabled", True),
            "policy": config.get("policy", "none"),
            "subdomain_policy": config.get("subdomain_policy"),
            "pct": config.get("pct", 100),
            "aspf": config.get("aspf", "r"),
            "adkim": config.get("adkim", "r"),
            "rua": config.get("rua") or [],
            "ruf": config.get("ruf") or [],
            "ri": config.get("ri", 86400),
            "notes": config.get("notes", ""),
            "record_value": config.get("record_value"),
        }
        existing = self._dmarc.get(domain)
        dmarc["created_at"] = existing.get("created_at", now) if existing else now
        dmarc["updated_at"] = now
        if not dmarc["record_value"]:
            dmarc["record_value"] = self.generate_dmarc_record(dmarc)
        self._dmarc[domain] = dmarc
        return dict(dmarc)

    def get_dmarc(self, domain: str) -> dict[str, Any] | None:
        dmarc = self._dmarc.get(domain.strip().lower())
        return dict(dmarc) if dmarc else None

    def list_dmarc(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._dmarc.values()]

    def update_dmarc(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        domain = domain.strip().lower()
        existing = self.get_dmarc(domain)
        if not existing:
            raise KeyError(domain)
        merged = {**existing, **{k: v for k, v in config.items() if v is not None}}
        merged["record_value"] = self.generate_dmarc_record(merged)
        merged["updated_at"] = _utcnow()
        self._dmarc[domain] = merged
        return dict(merged)

    def remove_dmarc(self, domain: str) -> bool:
        return self._dmarc.pop(domain.strip().lower(), None) is not None

    def validate_dmarc(self, domain: str) -> dict[str, Any]:
        domain = domain.strip().lower()
        config = self.get_dmarc(domain)
        fqdn = f"_dmarc.{domain}"
        expected = self.generate_dmarc_record(config) if config else "v=DMARC1; p=none"
        if config is None:
            return {
                "domain": domain,
                "is_valid": False,
                "dns_record_found": False,
                "record_value": None,
                "expected_record": expected,
                "errors": ["No DMARC policy configured for this domain"],
                "warnings": [],
                "dns_lookup_available": _DNSPYTHON_AVAILABLE,
                "checked_at": _utcnow(),
            }
        if _DNSPYTHON_AVAILABLE:
            try:
                answers = dns.resolver.resolve(fqdn, "TXT")
                record = "".join(
                    b.decode("utf-8", "ignore") if isinstance(b, bytes) else str(b)
                    for answer in answers
                    for b in answer.strings
                )
                return {
                    "domain": domain,
                    "is_valid": record.startswith("v=DMARC1"),
                    "dns_record_found": True,
                    "record_value": record,
                    "expected_record": expected,
                    "errors": [] if record.startswith("v=DMARC1") else ["DMARC record does not start with v=DMARC1"],
                    "warnings": [],
                    "dns_lookup_available": True,
                    "checked_at": _utcnow(),
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "domain": domain,
                    "is_valid": False,
                    "dns_record_found": False,
                    "record_value": None,
                    "expected_record": expected,
                    "errors": [f"DNS lookup failed: {exc}"],
                    "warnings": [],
                    "dns_lookup_available": True,
                    "checked_at": _utcnow(),
                }
        return {
            "domain": domain,
            "is_valid": False,
            "dns_record_found": False,
            "record_value": None,
            "expected_record": expected,
            "errors": ["dnspython not installed — live DNS validation unavailable"],
            "warnings": [],
            "dns_lookup_available": False,
            "checked_at": _utcnow(),
        }

    def add_dmarc_report(self, domain: str, report: dict[str, Any]) -> None:
        self._reports.setdefault(domain.strip().lower(), []).append(report)

    def get_dmarc_reports(self, domain: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._reports.get(domain.strip().lower(), [])]

    @staticmethod
    def parse_aggregate_report(xml_content: str) -> dict[str, Any]:
        """Parse a DMARC aggregate report XML payload."""
        root = ET.fromstring(xml_content)

        def _text(element: ET.Element | None, path: str) -> Any:
            if element is None:
                return None
            node = element.find(path)
            return node.text if node is not None else None

        metadata = root.find("report_metadata")
        policy = root.find("policy_published")
        parsed_policy = None
        if policy is not None:
            parsed_policy = {
                "domain": _text(policy, "domain"),
                "adkim": _text(policy, "adkim"),
                "aspf": _text(policy, "aspf"),
                "p": _text(policy, "p"),
                "sp": _text(policy, "sp"),
                "pct": int(_text(policy, "pct") or 0),
            }

        records: list[dict[str, Any]] = []
        for record in root.findall("record"):
            row = record.find("row")
            evaluated = row.find("policy_evaluated") if row is not None else None
            records.append({
                "source_ip": _text(row, "source_ip") if row is not None else None,
                "count": int(_text(row, "count") or 0),
                "disposition": _text(evaluated, "disposition"),
                "dkim": _text(evaluated, "dkim"),
                "spf": _text(evaluated, "spf"),
                "header_from": _text(record, "identifiers/header_from"),
            })

        return {
            "report_metadata": {
                "org_name": _text(metadata, "org_name"),
                "email": _text(metadata, "email"),
                "report_id": _text(metadata, "report_id"),
                "date_range_begin": _text(metadata, "date_range/begin"),
                "date_range_end": _text(metadata, "date_range/end"),
            },
            "policy_published": parsed_policy,
            "records": records,
        }

    # ── SPF ──────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_spf_record(config: dict[str, Any]) -> str:
        """Build the SPF DNS TXT value from a config."""
        parts = [config.get("version", "v=spf1")]
        raw = config.get("raw_mail_servers")
        if raw:
            parts.extend(str(raw).split())
        else:
            for domain in config.get("include_mechanisms") or []:
                parts.append(f"include:{domain}")
            for ip in config.get("ip4_mechanisms") or []:
                parts.append(f"ip4:{ip}")
            for ip in config.get("ip6_mechanisms") or []:
                parts.append(f"ip6:{ip}")
            for host in config.get("a_mechanisms") or []:
                parts.append(f"a:{host}" if host else "a")
            for host in config.get("mx_mechanisms") or []:
                parts.append(f"mx:{host}" if host else "mx")
            for host in config.get("exists_mechanisms") or []:
                parts.append(f"exists:{host}")
        if not config.get("raw_mail_servers") and config.get("all_qualifier") is None:
            parts.append("-all")
        if config.get("all_qualifier"):
            parts.append(config["all_qualifier"])
        if config.get("redirect_modifier"):
            parts.append(f"redirect={config['redirect_modifier']}")
        if config.get("explanation_modifier"):
            parts.append(f"explanation={config['explanation_modifier']}")
        return " ".join(parts)

    def set_spf(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        domain = domain.strip().lower()
        if domain not in self._domains:
            raise KeyError(domain)
        now = _utcnow()
        spf: dict[str, Any] = {
            "domain": domain,
            "enabled": config.get("enabled", True),
            "version": config.get("version", "v=spf1"),
            "include_mechanisms": config.get("include_mechanisms") or [],
            "ip4_mechanisms": config.get("ip4_mechanisms") or [],
            "ip6_mechanisms": config.get("ip6_mechanisms") or [],
            "a_mechanisms": config.get("a_mechanisms") or [],
            "mx_mechanisms": config.get("mx_mechanisms") or [],
            "exists_mechanisms": config.get("exists_mechanisms") or [],
            "raw_mail_servers": config.get("raw_mail_servers"),
            "all_qualifier": config.get("all_qualifier", "-all"),
            "redirect_modifier": config.get("redirect_modifier"),
            "explanation_modifier": config.get("explanation_modifier"),
            "notes": config.get("notes", ""),
            "record_value": config.get("record_value"),
        }
        existing = self._spf.get(domain)
        spf["created_at"] = existing.get("created_at", now) if existing else now
        spf["updated_at"] = now
        if not spf["record_value"]:
            spf["record_value"] = self.generate_spf_record(spf)
        self._spf[domain] = spf
        return dict(spf)

    def get_spf(self, domain: str) -> dict[str, Any] | None:
        spf = self._spf.get(domain.strip().lower())
        return dict(spf) if spf else None

    def list_spf(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._spf.values()]

    def update_spf(self, domain: str, config: dict[str, Any]) -> dict[str, Any]:
        domain = domain.strip().lower()
        existing = self.get_spf(domain)
        if not existing:
            raise KeyError(domain)
        merged = {**existing, **{k: v for k, v in config.items() if v is not None}}
        merged["record_value"] = self.generate_spf_record(merged)
        merged["updated_at"] = _utcnow()
        self._spf[domain] = merged
        return dict(merged)

    def remove_spf(self, domain: str) -> bool:
        return self._spf.pop(domain.strip().lower(), None) is not None

    def validate_spf(self, domain: str) -> dict[str, Any]:
        """Validate an SPF record: syntax, catch-all, DNS lookup limit."""
        domain = domain.strip().lower()
        config = self.get_spf(domain)
        fqdn = domain
        if config is None:
            return {
                "domain": domain,
                "is_valid": False,
                "dns_record_found": False,
                "record_value": None,
                "errors": ["No SPF record configured for this domain"],
                "warnings": [],
                "mechanism_count": 0,
                "dns_lookup_count": 0,
                "over_lookup_limit": False,
                "dns_lookup_available": _DNSPYTHON_AVAILABLE,
                "checked_at": _utcnow(),
            }

        errors: list[str] = []
        warnings: list[str] = []
        record = config.get("record_value") or self.generate_spf_record(config)
        parts = record.split()

        if not record.startswith("v=spf1"):
            errors.append("SPF record must start with 'v=spf1'")
        if not any(p in ("-all", "~all", "+all", "?all") for p in parts):
            errors.append("SPF record must end with a catch-all policy (-all, ~all, +all, or ?all)")
        if any(p in ("+all", "?all") for p in parts):
            warnings.append("Catch-all policy is permissive — consider -all or ~all")
        lookup_count = sum(
            1 for p in parts if p.startswith(("include:", "a:", "mx:", "ptr:", "exists:"))
        )
        if lookup_count > 10:
            errors.append(f"SPF record requires {lookup_count} DNS lookups (max 10 per RFC 7208)")
        elif lookup_count > 8:
            warnings.append(f"SPF record requires {lookup_count} DNS lookups (approaching limit of 10)")
        if any(p.startswith("ptr:") or p == "ptr" for p in parts):
            warnings.append("The 'ptr' mechanism is deprecated")

        result: dict[str, Any] = {
            "domain": domain,
            "is_valid": len(errors) == 0,
            "dns_record_found": False,
            "record_value": record,
            "expected_record": record,
            "errors": errors,
            "warnings": warnings,
            "mechanism_count": len(parts),
            "dns_lookup_count": lookup_count,
            "over_lookup_limit": lookup_count > 10,
            "dns_lookup_available": _DNSPYTHON_AVAILABLE,
            "checked_at": _utcnow(),
        }

        if _DNSPYTHON_AVAILABLE:
            try:
                answers = dns.resolver.resolve(fqdn, "TXT")
                live = " ".join(
                    b.decode("utf-8", "ignore") if isinstance(b, bytes) else str(b)
                    for answer in answers
                    for b in answer.strings
                )
                if "v=spf1" not in live:
                    result["errors"].append("No live SPF record found (TXT records do not contain v=spf1)")
                    result["is_valid"] = False
                else:
                    result["dns_record_found"] = True
                    result["record_value"] = live
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"DNS lookup failed: {exc}")
                result["is_valid"] = False
        return result

    # ── Test ─────────────────────────────────────────────────────────────────

    @staticmethod
    def test_email_auth(from_address: str, smtp_server: str = "localhost", smtp_port: int = 25) -> dict[str, Any]:
        """Best-effort SMTP authentication test (never raises)."""
        import smtplib

        domain = from_address.split("@")[-1] if "@" in from_address else from_address
        try:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=5) as server:
                code, msg = server.noop()
                return {
                    "sent": True,
                    "smtp_response": f"{code} {msg.decode('utf-8', 'ignore') if isinstance(msg, bytes) else msg}",
                    "domain": domain,
                    "from_address": from_address,
                    "timestamp": _utcnow(),
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "sent": False,
                "smtp_response": str(exc),
                "domain": domain,
                "from_address": from_address,
                "timestamp": _utcnow(),
            }
