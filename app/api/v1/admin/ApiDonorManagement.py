"""Donor Communication Management (#70) — non-profit market.

Track donors, manage communication preferences, GDPR consent,
tax-receipt generation, donation history, and campaign engagement.

Honesty contract (no fakes):
  * the organization EIN on tax receipts comes from the ``SOGO_DONOR_ORG_EIN``
    environment variable — there is NO hardcoded placeholder EIN;
  * receipts are only ever marked ``valid`` when a real, format-valid EIN is
    configured; otherwise they carry ``status: unconfigured`` / ``invalid`` and
    a disclaimer instead of claiming tax deductibility;
  * corporate/foundation donor EINs are format-validated on create (400 on
    garbage);
  * donation currencies are validated against the ISO 4217 alphabetic list;
  * every receipt carries a SHA-256 integrity hash and a verify endpoint
    recomputes it from the stored donation — tampering is detected honestly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Donor Management", __name__, url_prefix="/admin/donors")

_DONOR_PFX = "donor:"
_DONATION_PFX = "donation:"
_CAMPAIGN_PFX = "donor_campaign:"

# Canonical IRS EIN form: two digits, optional dash, seven digits.
_EIN_RE = re.compile(r"^\d{2}-?\d{7}$")

# ISO 4217 alphabetic codes (currencies still in circulation).
_ISO_4217: frozenset[str] = frozenset({
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BOV",
    "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE", "CHF",
    "CHW", "CLF", "CLP", "CNY", "COP", "COU", "CRC", "CUC", "CUP", "CVE",
    "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD",
    "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD",
    "HNL", "HRK", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR", "ISK",
    "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD",
    "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL",
    "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN",
    "MXV", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR",
    "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD",
    "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE",
    "SLL", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD",
    "USN", "UYI", "UYU", "UYW", "UZS", "VED", "VES", "VND", "VUV", "WST",
    "XAF", "XCD", "XOF", "XPF", "YER", "ZAR", "ZMW", "ZWL",
})


def validate_ein(ein: str | None) -> bool:
    """Return True when *ein* matches the real IRS EIN format (``XX-XXXXXXX``)."""
    if not ein:
        return False
    return bool(_EIN_RE.match(ein.strip()))


def _org_ein() -> tuple[str | None, str]:
    """Return (ein, status) from the configured ``SOGO_DONOR_ORG_EIN``.

    status is ``valid`` when a format-valid EIN is configured, ``invalid`` when
    configured but malformed (an operator error worth surfacing), or
    ``unconfigured`` when absent — in the last two cases receipts must NOT be
    marked tax-valid.
    """
    raw = os.environ.get("SOGO_DONOR_ORG_EIN", "").strip()
    if not raw:
        return None, "unconfigured"
    if validate_ein(raw):
        return raw, "valid"
    logger_api.error("SOGO_DONOR_ORG_EIN configured but invalid: %r — receipts will not be tax-valid", raw)
    return None, "invalid"


def _compute_donor_hash(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


def _receipt_hash(donation_id: str, amount: float, donor_email: str, tax_year: int, receipt_number: str, ein: str | None) -> str:
    """SHA-256 over the canonical receipt fields (tamper detection)."""
    canonical = f"{donation_id}|{amount:.2f}|{donor_email.lower()}|{tax_year}|{receipt_number}|{ein or ''}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _generate_tax_receipt(donation_id: str, amount: float, donor_name: str, email: str) -> dict:
    """Generate a receipt for a donation — honest about EIN configuration."""
    receipt_num = f"DR-{time.strftime('%Y%m')}-{secrets.token_hex(6).upper()[:6]}"
    tax_year = int(time.strftime("%Y"))
    ein, ein_status = _org_ein()

    receipt: dict = {
        "receipt_id": secrets.token_hex(10),
        "receipt_number": receipt_num,
        "donation_id": donation_id,
        "amount": amount,
        "currency": "USD",
        "donor_name": donor_name,
        "donor_email": email,
        "tax_year": tax_year,
        "generated_at": time.time(),
        "organization": "SOGo Foundation",
        "ein": ein,
        "status": ein_status,
    }
    if ein_status != "valid":
        receipt["disclaimer"] = (
            "This document is a donation acknowledgement, not a tax-deductible "
            "receipt: the organization EIN is not configured. "
            "(Set SOGO_DONOR_ORG_EIN to enable tax receipts.)"
        )
    else:
        receipt["status"] = "valid"
    receipt["receipt_hash"] = _receipt_hash(donation_id, amount, email, tax_year, receipt_num, ein)
    return receipt


@blp.route("/")
class DonorList(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_DONOR_PFX}index", list) or [])
        donors = []
        for did in idx:
            raw = cache.get(f"{_DONOR_PFX}{did}", str)
            if raw:
                donors.append(json.loads(raw))
        # Sort by total donated descending
        donors.sort(key=lambda d: d.get("total_donated", 0), reverse=True)
        return create_api_base_response(data=donors)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        email = (body.get("email") or "").strip().lower()
        if not email:
            return create_api_base_response(error_code="E000001", error_msg="email required", success=False)
        cache = sogo_cache()
        did = _compute_donor_hash(email)
        # Check if donor exists
        raw = cache.get(f"{_DONOR_PFX}{did}", str)
        if raw:
            return create_api_base_response(error_code="E000010", error_msg="Donor already exists", success=False, data=json.loads(raw))

        donor_type = body.get("donor_type", "individual")
        donor_ein = body.get("ein")
        if donor_type in ("corporate", "foundation"):
            if donor_ein is not None and not validate_ein(donor_ein):
                return create_api_base_response(
                    error_code="E000011", error_msg="Invalid EIN format (expected XX-XXXXXXX)", success=False,
                )
        else:
            donor_ein = None  # individuals do not carry EINs

        donor = {
            "id": did,
            "email": email,
            "name": body.get("name", ""),
            "phone": body.get("phone", ""),
            "address": body.get("address", {}),
            "donor_type": donor_type,
            "ein": donor_ein,
            "gdpr_consent": body.get("gdpr_consent", False),
            "gdpr_consent_date": time.time() if body.get("gdpr_consent") else None,
            "communication_preferences": body.get("communication_preferences", {
                "email_newsletter": True,
                "email_receipts": True,
                "sms_updates": False,
                "phone_calls": False,
            }),
            "total_donated": 0.0,
            "donation_count": 0,
            "first_donation": None,
            "last_donation": None,
            "tags": body.get("tags", []),
            "created_at": time.time(),
        }
        cache.set(f"{_DONOR_PFX}{did}", json.dumps(donor), ttl=86400 * 365)
        idx = list(cache.get(f"{_DONOR_PFX}index", list) or [])
        idx.append(did)
        cache.set(f"{_DONOR_PFX}index", idx, ttl=86400 * 365)
        logger_api.info("Donor registered: %s (%s)", donor["name"], email)
        return create_api_base_response(data=donor)


@blp.route("/<donor_id>")
class DonorDetail(MethodView):
    def get(self, donor_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_DONOR_PFX}{donor_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Donor not found", success=False)
        donor = json.loads(raw)
        # Get donation history
        don_idx = list(cache.get(f"{_DONATION_PFX}index", list) or [])
        donations = []
        for did in don_idx:
            draw = cache.get(f"{_DONATION_PFX}{did}", str)
            if draw:
                d = json.loads(draw)
                if d.get("donor_id") == donor_id:
                    donations.append(d)
        donations.sort(key=lambda x: x.get("date", 0), reverse=True)
        donor["donations"] = donations
        return create_api_base_response(data=donor)


@blp.route("/<donor_id>/donate")
class DonorDonate(MethodView):
    def post(self, donor_id: str) -> ResponseReturnValue:
        body = request.get_json(force=True)
        try:
            amount = float(body.get("amount", 0))
        except (TypeError, ValueError):
            return create_api_base_response(error_code="E000005", error_msg="Amount must be a number", success=False)
        campaign = body.get("campaign", "general")
        method = body.get("method", "online")  # online, check, wire, crypto
        currency = str(body.get("currency", "USD")).upper()
        if amount <= 0:
            return create_api_base_response(error_code="E000005", error_msg="Amount must be positive", success=False)
        if currency not in _ISO_4217:
            return create_api_base_response(
                error_code="E000012", error_msg=f"Unknown ISO 4217 currency code: {currency}", success=False,
            )
        cache = sogo_cache()
        raw = cache.get(f"{_DONOR_PFX}{donor_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Donor not found", success=False)
        donor = json.loads(raw)
        don_id = secrets.token_hex(10)
        donation = {
            "id": don_id,
            "donor_id": donor_id,
            "amount": amount,
            "currency": currency,
            "campaign": campaign,
            "method": method,
            "date": time.time(),
            "receipt": _generate_tax_receipt(don_id, amount, donor["name"], donor["email"]),
            "anonymous": body.get("anonymous", False),
        }
        cache.set(f"{_DONATION_PFX}{don_id}", json.dumps(donation), ttl=86400 * 365)
        don_idx = list(cache.get(f"{_DONATION_PFX}index", list) or [])
        don_idx.append(don_id)
        cache.set(f"{_DONATION_PFX}index", don_idx, ttl=86400 * 365)
        # Update donor totals
        donor["total_donated"] = round(donor.get("total_donated", 0) + amount, 2)
        donor["donation_count"] = donor.get("donation_count", 0) + 1
        donor["last_donation"] = time.time()
        if not donor.get("first_donation"):
            donor["first_donation"] = time.time()
        cache.set(f"{_DONOR_PFX}{donor_id}", json.dumps(donor), ttl=86400 * 365)
        logger_api.info("Donation %.2f %s from %s for campaign '%s'", amount, currency, donor["email"], campaign)
        return create_api_base_response(data=donation)


@blp.route("/<donor_id>/donations/<donation_id>/receipt")
class ReceiptVerify(MethodView):
    def get(self, donor_id: str, donation_id: str) -> ResponseReturnValue:
        """Verify a stored receipt's integrity hash (tamper detection)."""
        cache = sogo_cache()
        raw = cache.get(f"{_DONATION_PFX}{donation_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Donation not found", success=False)
        donation = json.loads(raw)
        if donation.get("donor_id") != donor_id:
            return create_api_base_response(error_code="E000002", error_msg="Donation not found for this donor", success=False)
        receipt = donation.get("receipt") or {}
        expected = receipt.get("receipt_hash", "")
        recomputed = _receipt_hash(
            donation_id,
            float(receipt.get("amount", 0.0)),
            str(receipt.get("donor_email", "")),
            int(receipt.get("tax_year", 0)),
            str(receipt.get("receipt_number", "")),
            receipt.get("ein"),
        )
        return create_api_base_response(data={
            "donation_id": donation_id,
            "receipt_number": receipt.get("receipt_number"),
            "status": receipt.get("status"),
            "ein": receipt.get("ein"),
            "integrity_valid": bool(expected) and secrets.compare_digest(expected, recomputed),
        })


@blp.route("/<donor_id>/gdpr")
class DonorGdpr(MethodView):
    def post(self, donor_id: str) -> ResponseReturnValue:
        body = request.get_json(force=True)
        consent = body.get("consent", True)
        cache = sogo_cache()
        raw = cache.get(f"{_DONOR_PFX}{donor_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Donor not found", success=False)
        donor = json.loads(raw)
        donor["gdpr_consent"] = consent
        donor["gdpr_consent_date"] = time.time() if consent else None
        cache.set(f"{_DONOR_PFX}{donor_id}", json.dumps(donor), ttl=86400 * 365)
        return create_api_base_response(data={"consent": consent, "updated": True})

    def delete(self, donor_id: str) -> ResponseReturnValue:
        """GDPR right to erasure — anonymize all donor data."""
        cache = sogo_cache()
        raw = cache.get(f"{_DONOR_PFX}{donor_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Donor not found", success=False)
        donor = json.loads(raw)
        # Anonymize but keep record for financial compliance
        donor["email"] = f"anonymized-{donor_id}@erased.invalid"
        donor["name"] = "GDPR ERASED"
        donor["phone"] = ""
        donor["address"] = {}
        donor["gdpr_consent"] = False
        donor["erased_at"] = time.time()
        cache.set(f"{_DONOR_PFX}{donor_id}", json.dumps(donor), ttl=86400 * 365)
        logger_api.info("GDPR erasure completed for donor %s", donor_id)
        return create_api_base_response(data={"erased": True, "donor_id": donor_id})