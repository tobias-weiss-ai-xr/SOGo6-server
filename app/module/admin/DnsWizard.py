from __future__ import annotations

from typing import Any


class DnsWizard:
    """Generates DNS records for email authentication (SPF, DKIM, DMARC).

    Provides helper methods to construct properly formatted DNS records
    that administrators can add to their domain's DNS zone.
    """

    # Common SPF mechanisms
    SPF_MX = "mx"
    SPF_A = "a"
    SPF_ALL = ["a", "mx", "ip4", "ip6", "include", "exists"]

    @staticmethod
    def generate_spf_record(
        domain: str,
        mx_servers: list[str] | None = None,
        ip4_addresses: list[str] | None = None,
        ip6_addresses: list[str] | None = None,
        include_domains: list[str] | None = None,
        policy: str = "~all",
    ) -> dict[str, str]:
        """Generate an SPF TXT record for the given domain.

        :param domain: The domain name (e.g., example.org).
        :param mx_servers: Optional list of MX server hostnames.
        :param ip4_addresses: Optional list of IPv4 addresses.
        :param ip6_addresses: Optional list of IPv6 addresses.
        :param include_domains: Optional list of domains to include via ``include:``.
        :param policy: The catch-all policy (``~all`` for softfail, ``-all`` for hardfail, ``+all`` for neutral).
        :return: Dict with ``name``, ``type``, ``value``, ``ttl``.
        """
        mechanisms: list[str] = ["v=spf1"]

        if mx_servers:
            mechanisms.append("mx")
        else:
            mechanisms.append("mx")  # Default: allow domain MX servers

        if ip4_addresses:
            for ip in ip4_addresses:
                mechanisms.append(f"ip4:{ip}")

        if ip6_addresses:
            for ip in ip6_addresses:
                mechanisms.append(f"ip6:{ip}")

        if include_domains:
            for dom in include_domains:
                mechanisms.append(f"include:{dom}")

        mechanisms.append(policy)

        return {
            "name": domain,
            "type": "TXT",
            "value": " ".join(mechanisms),
            "ttl": 3600,
            "description": f"SPF record for {domain} — authorizes which servers may send email from this domain.",
        }

    @staticmethod
    def generate_dkim_record(
        domain: str,
        selector: str = "sogo",
        key_type: str = "ed25519",
        public_key: str | None = None,
    ) -> dict[str, Any]:
        """Generate a DKIM TXT record.

        :param domain: The domain name.
        :param selector: The DKIM selector (default: ``sogo``).
        :param key_type: Key type (``ed25519`` or ``rsa``).
        :param public_key: Base64-encoded public key. If None, a placeholder is returned
            indicating the key needs to be generated.
        :return: Dict with ``name``, ``type``, ``value``, ``ttl``, ``selector``.
        """
        if public_key:
            dkim_value = f"v=DKIM1; k={key_type}; p={public_key}"
        else:
            dkim_value = (
                f"v=DKIM1; k={key_type}; p="
                f"<REPLACE_WITH_PUBLIC_KEY>  "
                f"# Generate with: openssl genpkey -algorithm {key_type.upper()} -out {selector}.key && "
                f"openssl pkey -in {selector}.key -pubout -outform DER | base64"
            )

        return {
            "name": f"{selector}._domainkey.{domain}",
            "type": "TXT",
            "value": dkim_value,
            "ttl": 3600,
            "selector": selector,
            "description": f"DKIM record for {domain} using selector '{selector}' ({key_type}).",
        }

    @staticmethod
    def generate_dmarc_record(
        domain: str,
        policy: str = "none",
        rua_email: str | None = None,
        ruf_email: str | None = None,
        pct: int = 100,
        subdomain_policy: str | None = None,
        aspf: str = "r",
        adkim: str = "r",
    ) -> dict[str, Any]:
        """Generate a DMARC TXT record.

        :param domain: The domain name.
        :param policy: Domain policy (``none``, ``quarantine``, ``reject``).
        :param rua_email: Email address for aggregate feedback reports (``dmarc@example.org``).
        :param ruf_email: Email address for forensic feedback reports (optional).
        :param pct: Percentage of messages subject to filtering (1-100).
        :param subdomain_policy: Policy for subdomains (``none``, ``quarantine``, ``reject``).
            If None, inherits the domain policy.
        :param aspf: SPF alignment mode (``r`` relaxed, ``s`` strict).
        :param adkim: DKIM alignment mode (``r`` relaxed, ``s`` strict).
        :return: Dict with ``name``, ``type``, ``value``, ``ttl``.
        """
        tags: list[str] = ["v=DMARC1", f"p={policy}", f"pct={pct}", f"aspf={aspf}", f"adkim={adkim}"]

        if subdomain_policy:
            tags.append(f"sp={subdomain_policy}")

        if rua_email:
            tags.append(f"rua=mailto:{rua_email}")

        if ruf_email:
            tags.append(f"ruf=mailto:{ruf_email}")

        return {
            "name": f"_dmarc.{domain}",
            "type": "TXT",
            "value": "; ".join(tags),
            "ttl": 3600,
            "description": f"DMARC record for {domain} (policy: {policy}). "
                           f"Start with p=none, monitor reports, then move to p=quarantine or p=reject.",
        }

    @staticmethod
    def validate_spf(spf_value: str) -> dict[str, Any]:
        """Validate an SPF record value and return any issues found.

        :param spf_value: The SPF TXT record value (e.g., ``v=spf1 mx ~all``).
        :return: Dict with ``valid`` (bool), ``warnings`` (list), ``errors`` (list).
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not spf_value.startswith("v=spf1"):
            errors.append("SPF record must start with 'v=spf1'")

        parts = spf_value.split()
        if len(parts) < 2:
            errors.append("SPF record too short — expected mechanisms after v=spf1")

        has_all = any(p in ("-all", "~all", "+all", "?all") for p in parts)
        if not has_all:
            errors.append("SPF record must end with a catch-all policy (-all, ~all, +all, or ?all)")

        # Check for too many DNS lookups (SPF spec limit: 10)
        lookup_count = sum(1 for p in parts if p.startswith(("include:", "a:", "mx:", "ptr:", "exists:")))
        if lookup_count > 10:
            errors.append(f"SPF record requires {lookup_count} DNS lookups (max 10 per RFC 7208)")
        elif lookup_count > 8:
            warnings.append(f"SPF record requires {lookup_count} DNS lookups (approaching limit of 10)")

        # Warn about ptr mechanism (deprecated)
        if any(p.startswith("ptr:") or p == "ptr" for p in parts):
            warnings.append("The 'ptr' mechanism is deprecated and should not be used")

        return {"valid": len(errors) == 0, "warnings": warnings, "errors": errors}

    @staticmethod
    def validate_dmarc(dmarc_value: str) -> dict[str, Any]:
        """Validate a DMARC record value and return any issues found.

        :param dmarc_value: The DMARC TXT record value.
        :return: Dict with ``valid`` (bool), ``warnings`` (list), ``errors`` (list).
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not dmarc_value.startswith("v=DMARC1"):
            errors.append("DMARC record must start with 'v=DMARC1'")

        tags = dict(
            part.split("=", 1) for part in dmarc_value.split(";")
            if "=" in part
        )

        policy = tags.get("p", "").strip()
        if policy not in ("none", "quarantine", "reject"):
            errors.append(f"Invalid DMARC policy '{policy}' — must be 'none', 'quarantine', or 'reject'")

        if policy == "none":
            warnings.append("DMARC policy is 'none' — monitoring only, no enforcement")

        pct_str = tags.get("pct", "").strip()
        if pct_str:
            try:
                pct_val = int(pct_str)
                if pct_val < 1 or pct_val > 100:
                    errors.append(f"DMARC pct must be between 1 and 100, got {pct_val}")
            except ValueError:
                errors.append(f"Invalid DMARC pct value '{pct_str}'")

        return {"valid": len(errors) == 0, "warnings": warnings, "errors": errors}
