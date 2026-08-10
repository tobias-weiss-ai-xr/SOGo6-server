"""Donor Management (#11) — real EIN handling + receipt integrity tests.

No hardcoded placeholder EIN may ever appear on a receipt: receipts are
``valid`` only when ``SOGO_DONOR_ORG_EIN`` is set to a format-valid EIN,
donor EINs are validated, currencies are ISO-4217-checked, and the receipt
integrity hash catches tampering.
"""
from __future__ import annotations

import json
import secrets

import pytest

from app import create_app
from app.utils import constants as cs

BASE = "/api/admin/v1/admin/donors"


@pytest.fixture()
def admin_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    return app.test_client()


def _auth():
    return {"Authorization": "Bearer test-token"}


def _mk_donor(client, email=None, **overrides):
    email = email or f"donor-{secrets.token_hex(4)}@example.org"
    payload = {
        "email": email,
        "name": "Test Donor",
        "donor_type": "individual",
        "gdpr_consent": True,
    }
    payload.update(overrides)
    resp = client.post(f"{BASE}/", json=payload, headers=_auth())  # collection route has trailing slash
    assert resp.status_code == 200
    return resp.get_json()["data"]


def _donate(client, donor_id, amount=50.0, **overrides):
    payload = {"amount": amount, "campaign": "annual", "method": "online"}
    payload.update(overrides)
    resp = client.post(f"{BASE}/{donor_id}/donate", json=payload, headers=_auth())
    assert resp.status_code == 200
    return resp.get_json()["data"]


# --------------------------------------------------------------------- #
# validate_ein unit behaviour
# --------------------------------------------------------------------- #

def test_validate_ein_cases():
    from app.api.v1.admin.ApiDonorManagement import validate_ein

    assert validate_ein("12-3456789")
    assert validate_ein("123456789")
    assert not validate_ein(None)
    assert not validate_ein("")
    assert not validate_ein("12-345678")
    assert not validate_ein("123")
    assert not validate_ein("abc-1234567")
    assert not validate_ein("1234567890")


# --------------------------------------------------------------------- #
# donor lifecycle
# --------------------------------------------------------------------- #

def test_create_donor(admin_client):
    email = f"alice-{secrets.token_hex(4)}@example.org"
    data = _mk_donor(admin_client, email=email)
    assert data["email"] == email
    assert data["donor_type"] == "individual"
    assert data["ein"] is None
    assert data["total_donated"] == 0.0
    assert len(data["id"]) == 16


def test_create_duplicate_rejected(admin_client):
    email = f"dup-{secrets.token_hex(4)}@example.org"
    _mk_donor(admin_client, email=email)
    resp = admin_client.post(f"{BASE}/", json={"email": email.upper(), "name": "x"}, headers=_auth())
    assert resp.status_code == 400
    assert "already exists" in json.dumps(resp.get_json())


def test_create_requires_email(admin_client):
    resp = admin_client.post(f"{BASE}/", json={"name": "no email"}, headers=_auth())
    assert resp.status_code == 400


def test_corporate_donor_valid_ein_stored(admin_client):
    data = _mk_donor(admin_client, donor_type="corporate", ein="45-6789012")
    assert data["ein"] == "45-6789012"


def test_corporate_donor_invalid_ein_rejected(admin_client):
    resp = admin_client.post(
        f"{BASE}/",
        json={"email": f"corp-{secrets.token_hex(4)}@example.org", "name": "Corp", "donor_type": "corporate", "ein": "123"},
        headers=_auth(),
    )
    assert resp.status_code == 400
    assert "E000011" in json.dumps(resp.get_json())


def test_individual_donor_ein_not_stored(admin_client):
    data = _mk_donor(admin_client, donor_type="individual", ein="12-3456789")
    assert data["ein"] is None


def test_donor_list_sorted_by_total(admin_client):
    a = _mk_donor(admin_client)
    b = _mk_donor(admin_client)
    _donate(admin_client, a["id"], amount=10.0)
    _donate(admin_client, b["id"], amount=200.0)
    resp = admin_client.get(f"{BASE}/", headers=_auth())
    donors = resp.get_json()["data"]
    totals = [d["total_donated"] for d in donors if d["id"] in (a["id"], b["id"])]
    assert totals == sorted(totals, reverse=True)


# --------------------------------------------------------------------- #
# donations & receipts — honest EIN handling
# --------------------------------------------------------------------- #

def test_donate_receipt_unconfigured_when_no_ein(admin_client, monkeypatch):
    monkeypatch.delenv("SOGO_DONOR_ORG_EIN", raising=False)
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"], amount=100.0, currency="EUR")
    receipt = donation["receipt"]
    assert receipt["status"] == "unconfigured"
    assert receipt["ein"] is None
    assert "not a tax-deductible" in receipt["disclaimer"].lower()
    assert receipt["amount"] == 100.0
    assert receipt["receipt_number"].startswith("DR-")


def test_donate_receipt_valid_with_configured_ein(admin_client, monkeypatch):
    monkeypatch.setenv("SOGO_DONOR_ORG_EIN", "12-3456789")
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"])
    receipt = donation["receipt"]
    assert receipt["status"] == "valid"
    assert receipt["ein"] == "12-3456789"
    assert "disclaimer" not in receipt
    assert receipt["receipt_hash"]
    # donor totals updated
    resp = admin_client.get(f"{BASE}/{donor['id']}", headers=_auth())
    donor_after = resp.get_json()["data"]
    assert donor_after["total_donated"] == 50.0
    assert donor_after["donation_count"] == 1


def test_donate_receipt_invalid_with_malformed_ein(admin_client, monkeypatch):
    monkeypatch.setenv("SOGO_DONOR_ORG_EIN", "not-an-ein")
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"])
    assert donation["receipt"]["status"] == "invalid"
    assert donation["receipt"]["ein"] is None


def test_donate_rejects_non_positive(admin_client):
    donor = _mk_donor(admin_client)
    resp = admin_client.post(f"{BASE}/{donor['id']}/donate", json={"amount": -5}, headers=_auth())
    assert resp.status_code == 400
    resp0 = admin_client.post(f"{BASE}/{donor['id']}/donate", json={"amount": 0}, headers=_auth())
    assert resp0.status_code == 400


def test_donate_rejects_unknown_currency(admin_client):
    donor = _mk_donor(admin_client)
    resp = admin_client.post(f"{BASE}/{donor['id']}/donate", json={"amount": 10, "currency": "XYZ"}, headers=_auth())
    assert resp.status_code == 400
    assert "E000012" in json.dumps(resp.get_json())


def test_donate_normalizes_currency_case(admin_client):
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"], currency="eur")
    assert donation["currency"] == "EUR"


# --------------------------------------------------------------------- #
# receipt integrity verification
# --------------------------------------------------------------------- #

def test_receipt_verify_valid(admin_client, monkeypatch):
    monkeypatch.setenv("SOGO_DONOR_ORG_EIN", "12-3456789")
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"], amount=75.0)
    resp = admin_client.get(
        f"{BASE}/{donor['id']}/donations/{donation['id']}/receipt", headers=_auth()
    )
    data = resp.get_json()["data"]
    assert data["integrity_valid"] is True
    assert data["status"] == "valid"


def test_receipt_verify_detects_tampering(admin_client, monkeypatch):
    monkeypatch.setenv("SOGO_DONOR_ORG_EIN", "12-3456789")
    donor = _mk_donor(admin_client)
    donation = _donate(admin_client, donor["id"], amount=75.0)

    # adversarially rewrite the stored receipt amount (faking a bigger receipt)
    from app.service import sogo_cache
    cache = sogo_cache()
    raw = cache.get(f"donation:{donation['id']}", str)
    stored = json.loads(raw)
    stored["receipt"]["amount"] = 9999.0
    cache.set(f"donation:{donation['id']}", json.dumps(stored), ttl=86400 * 365)

    resp = admin_client.get(
        f"{BASE}/{donor['id']}/donations/{donation['id']}/receipt", headers=_auth()
    )
    assert resp.get_json()["data"]["integrity_valid"] is False


# --------------------------------------------------------------------- #
# GDPR
# --------------------------------------------------------------------- #

def test_gdpr_erasure_anonymizes(admin_client):
    donor = _mk_donor(admin_client)
    resp = admin_client.delete(f"{BASE}/{donor['id']}/gdpr", headers=_auth())
    assert resp.get_json()["data"]["erased"] is True
    detail = admin_client.get(f"{BASE}/{donor['id']}", headers=_auth()).get_json()["data"]
    assert detail["name"] == "GDPR ERASED"
    assert detail["email"].endswith("@erased.invalid")
    assert detail["gdpr_consent"] is False


def test_gdpr_consent_toggle(admin_client):
    donor = _mk_donor(admin_client, gdpr_consent=False)
    resp = admin_client.post(f"{BASE}/{donor['id']}/gdpr", json={"consent": True}, headers=_auth())
    assert resp.get_json()["data"]["consent"] is True
    detail = admin_client.get(f"{BASE}/{donor['id']}", headers=_auth()).get_json()["data"]
    assert detail["gdpr_consent"] is True
    assert detail["gdpr_consent_date"] is not None