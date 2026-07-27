"""Donor Communication Management (#70) — non-profit market.

Track donors, manage communication preferences, GDPR consent, 
tax-receipt generation, donation history, and campaign engagement.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

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


def _compute_donor_hash(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


def _generate_tax_receipt(donation_id: str, amount: float, donor_name: str, email: str) -> dict:
    """Generate a tax-deductible receipt for a donation."""
    receipt_num = f"DR-{time.strftime('%Y%m')}-{secrets.token_hex(6).upper()[:6]}"
    return {
        "receipt_id": secrets.token_hex(10),
        "receipt_number": receipt_num,
        "donation_id": donation_id,
        "amount": amount,
        "currency": "USD",
        "donor_name": donor_name,
        "donor_email": email,
        "tax_year": int(time.strftime("%Y")),
        "generated_at": time.time(),
        "organization": "SOGo Foundation",
        "ein": "XX-XXXXXXX",  # placeholder EIN
        "status": "valid",
    }


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
        donor = {
            "id": did,
            "email": email,
            "name": body.get("name", ""),
            "phone": body.get("phone", ""),
            "address": body.get("address", {}),
            "donor_type": body.get("donor_type", "individual"),  # individual, corporate, foundation
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
        amount = float(body.get("amount", 0))
        campaign = body.get("campaign", "general")
        method = body.get("method", "online")  # online, check, wire, crypto
        if amount <= 0:
            return create_api_base_response(error_code="E000005", error_msg="Amount must be positive", success=False)
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
            "currency": body.get("currency", "USD"),
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
        logger_api.info("Donation $%.2f from %s for campaign '%s'", amount, donor["email"], campaign)
        return create_api_base_response(data=donation)


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
