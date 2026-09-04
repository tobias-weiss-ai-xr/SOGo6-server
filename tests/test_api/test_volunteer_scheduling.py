# pylint: disable=invalid-sequence-index
"""Functional tests for ApiVolunteerScheduling (22% -> high).

Registers the real blueprint on a Flask test app, patches the module-level
``sogo_cache`` with an in-memory cache, and exercises the full volunteer /
shift / checkin / checkout / certificate lifecycle plus error branches.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from unittest.mock import patch

import pytest
from flask import Flask

from app.api.v1.admin.ApiVolunteerScheduling import blp


class FakeCache:
    def __init__(self):
        self.store = {}

    def set(self, key, val, ttl=None, nx=False):
        self.store[key] = val
        return True

    def get(self, key, expected_type=None):
        return self.store.get(key)

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)


@pytest.fixture
def cache():
    return FakeCache()


@pytest.fixture
def client(cache):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)
    app.json.ensure_ascii = False
    with patch("app.api.v1.admin.ApiVolunteerScheduling.sogo_cache", return_value=cache):
        yield app.test_client()


def _json_body(data):
    return data


# ─────────────────────────────────────────────────────────────────────────────
# VolunteerList
# ─────────────────────────────────────────────────────────────────────────────

class TestVolunteerList:
    def test_empty_list(self, client):
        r = client.get("/admin/volunteers/")
        assert r.status_code == 200
        body = r.get_json()
        assert body["data"] == []

    def test_register_and_list(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "Alice@Example.org", "name": "Alice"})
        assert r.status_code == 200
        vol = r.get_json()["data"]
        assert vol["email"] == "alice@example.org"
        assert vol["name"] == "Alice"
        assert vol["status"] == "active"
        assert vol["no_show_count"] == 0
        assert vol["total_hours"] == 0
        assert vol["certificates"] == []
        assert "created_at" in vol
        # index maintained
        assert cache.store["vol:index"] == [vol["id"]]

        r = client.get("/admin/volunteers/")
        body = r.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == vol["id"]

    def test_register_requires_email_and_name(self, client):
        r = client.post("/admin/volunteers/", json={"email": "", "name": ""})
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000003"
        r = client.post("/admin/volunteers/", json={"email": "a@b.c"})
        assert r.status_code == 400

    def test_register_with_defaults(self, client):
        r = client.post("/admin/volunteers/", json={"email": "bob@example.org", "name": "Bob"})
        vol = r.get_json()["data"]
        assert vol["max_hours_per_week"] == 20
        assert vol["availability"]["monday"] == []
        assert vol["skills"] == []

    def test_register_with_custom_fields(self, client):
        r = client.post(
            "/admin/volunteers/",
            json={
                "email": "carol@example.org",
                "name": "Carol",
                "phone": "+49",
                "skills": ["first aid"],
                "max_hours_per_week": 8,
                "availability": {"monday": [9, 10]},
            },
        )
        vol = r.get_json()["data"]
        assert vol["phone"] == "+49"
        assert vol["skills"] == ["first aid"]
        assert vol["max_hours_per_week"] == 8
        assert vol["availability"] == {"monday": [9, 10]}

    def test_total_hours_computed_from_logs(self, client, cache):
        # register volunteer
        r = client.post("/admin/volunteers/", json={"email": "d@example.org", "name": "D"})
        vid = r.get_json()["data"]["id"]
        # seed a completed log for this volunteer + one for another + another status
        cache.set("vol_log:l1", json.dumps({
            "volunteer_id": vid, "status": "completed", "hours": 2.5, "id": "l1"}))
        cache.set("vol_log:l2", json.dumps({
            "volunteer_id": vid, "status": "completed", "hours": 1.5, "id": "l2"}))
        cache.set("vol_log:l3", json.dumps({
            "volunteer_id": vid, "status": "scheduled", "hours": 99.0, "id": "l3"}))
        cache.set("vol_log:l4", json.dumps({
            "volunteer_id": "other", "status": "completed", "hours": 99.0, "id": "l4"}))
        cache.set("vol_log:index", ["l1", "l2", "l3", "l4"])
        r = client.get("/admin/volunteers/")
        assert r.status_code == 200
        vol = r.get_json()["data"][0]
        assert vol["total_hours"] == 4.0

    def test_list_sorts_by_total_hours_desc(self, client, cache):
        r1 = client.post("/admin/volunteers/", json={"email": "a@example.org", "name": "A"})
        r2 = client.post("/admin/volunteers/", json={"email": "b@example.org", "name": "B"})
        v1, v2 = r1.get_json()["data"]["id"], r2.get_json()["data"]["id"]
        cache.set("vol_log:la", json.dumps({"volunteer_id": v1, "status": "completed", "hours": 5, "id": "la"}))
        cache.set("vol_log:index", ["la"])
        r = client.get("/admin/volunteers/")
        ids = [v["id"] for v in r.get_json()["data"]]
        assert ids == [v1, v2]


# ─────────────────────────────────────────────────────────────────────────────
# VolunteerDetail
# ─────────────────────────────────────────────────────────────────────────────

class TestVolunteerDetail:
    def test_get_missing(self, client):
        r = client.get("/admin/volunteers/nope")
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000002"

    def test_get_with_shifts(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "e@example.org", "name": "E"})
        vid = r.get_json()["data"]["id"]
        cache.set("vol_shift:s1", json.dumps({"volunteer_id": vid, "start_time": 200, "id": "s1"}))
        cache.set("vol_shift:s2", json.dumps({"volunteer_id": "other", "start_time": 100, "id": "s2"}))
        cache.set("vol_shift:index", ["s2", "s1"])
        r = client.get(f"/admin/volunteers/{vid}")
        assert r.status_code == 200
        shifts = r.get_json()["data"]["shifts"]
        assert [s["id"] for s in shifts] == ["s1"]


# ─────────────────────────────────────────────────────────────────────────────
# ShiftList
# ─────────────────────────────────────────────────────────────────────────────

class TestShiftList:
    def test_get_empty(self, client):
        r = client.get("/admin/volunteers/shifts")
        assert r.status_code == 200
        assert r.get_json()["data"] == []

    def test_get_sorted(self, client, cache):
        cache.set("vol_shift:s1", json.dumps({"id": "s1", "start_time": 300}))
        cache.set("vol_shift:s2", json.dumps({"id": "s2", "start_time": 100}))
        cache.set("vol_shift:index", ["s1", "s2"])
        r = client.get("/admin/volunteers/shifts")
        assert [s["id"] for s in r.get_json()["data"]] == ["s2", "s1"]

    def test_post_requires_fields(self, client):
        r = client.post("/admin/volunteers/shifts", json={})
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000003"

    def test_post_end_before_start(self, client):
        r = client.post("/admin/volunteers/shifts",
                        json={"volunteer_id": "v", "start_time": 100, "end_time": 50})
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000006"

    def test_post_conflict(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "f@example.org", "name": "F"})
        vid = r.get_json()["data"]["id"]
        # existing assigned overlapping shift
        cache.set("vol_shift:s1", json.dumps({
            "id": "s1", "volunteer_id": vid, "status": "assigned",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:index", ["s1"])
        r = client.post("/admin/volunteers/shifts",
                        json={"volunteer_id": vid, "start_time": 1500, "end_time": 2500})
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000007"
        assert "conflicts" in r.get_json().get("data", {})

    def test_post_no_conflict_with_non_overlap(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "g@example.org", "name": "G"})
        vid = r.get_json()["data"]["id"]
        cache.set("vol_shift:s1", json.dumps({
            "id": "s1", "volunteer_id": vid, "status": "assigned",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:index", ["s1"])
        r = client.post("/admin/volunteers/shifts",
                        json={"volunteer_id": vid, "start_time": 2000, "end_time": 3000})
        assert r.status_code == 200
        shift = r.get_json()["data"]
        assert shift["hours"] == round(1000 / 3600.0, 1)
        assert shift["status"] == "scheduled"
        assert cache.store["vol_shift:index"] == ["s1", shift["id"]]

    def test_post_with_custom_fields(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "h@example.org", "name": "H"})
        vid = r.get_json()["data"]["id"]
        r = client.post("/admin/volunteers/shifts", json={
            "volunteer_id": vid, "start_time": 100, "end_time": 3600,
            "location": "Hall", "task": "usher", "status": "assigned", "notes": "n"})
        shift = r.get_json()["data"]
        assert shift["location"] == "Hall"
        assert shift["task"] == "usher"
        assert shift["status"] == "assigned"
        assert shift["notes"] == "n"


# ─────────────────────────────────────────────────────────────────────────────
# ShiftCheckin / ShiftCheckout
# ─────────────────────────────────────────────────────────────────────────────

class TestShiftCheckinCheckout:
    def _make_shift(self, client, cache, vid=None):
        if vid is None:
            r = client.post("/admin/volunteers/", json={"email": "i@example.org", "name": "I"})
            vid = r.get_json()["data"]["id"]
        r = client.post("/admin/volunteers/shifts", json={
            "volunteer_id": vid, "start_time": 1000, "end_time": 8200})
        return r.get_json()["data"]["id"]

    def test_checkin_missing(self, client):
        r = client.post("/admin/volunteers/shifts/nope/checkin")
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000002"

    def test_checkin_ok(self, client, cache):
        sid = self._make_shift(client, cache)
        r = client.post(f"/admin/volunteers/shifts/{sid}/checkin")
        assert r.status_code == 200
        shift = r.get_json()["data"]
        assert shift["status"] == "in_progress"
        assert "checkin_time" in shift

    def test_checkout_missing(self, client):
        r = client.post("/admin/volunteers/shifts/nope/checkout", json={"notes": ""})
        assert r.status_code == 400

    def test_checkout_ok_creates_log(self, client, cache):
        sid = self._make_shift(client, cache)
        client.post(f"/admin/volunteers/shifts/{sid}/checkin")
        r = client.post(f"/admin/volunteers/shifts/{sid}/checkout", json={"notes": "done"})
        assert r.status_code == 200
        log = r.get_json()["data"]
        assert log["status"] == "completed"
        assert log["shift_id"] == sid
        assert log["notes"] == "done"
        assert "volunteer_id" in log
        # stored in log index
        assert cache.store["vol_log:index"] == [log["id"]]
        # shift updated
        shift_raw = cache.store[f"vol_shift:{sid}"]
        shift = json.loads(shift_raw)
        assert shift["status"] == "completed"
        assert "checkout_time" in shift
        assert "actual_hours" in shift

    def test_checkout_without_checkin_uses_start_time(self, client, cache):
        sid = self._make_shift(client, cache)
        r = client.post(f"/admin/volunteers/shifts/{sid}/checkout", json={})
        assert r.status_code == 200
        log = r.get_json()["data"]
        assert log["status"] == "completed"


# ─────────────────────────────────────────────────────────────────────────────
# VolunteerCertificate
# ─────────────────────────────────────────────────────────────────────────────

class TestVolunteerCertificate:
    def test_certificate_missing_volunteer(self, client):
        r = client.post("/admin/volunteers/nope/certificate")
        assert r.status_code == 400
        assert r.get_json()["error_code"] == "E000002"

    def test_certificate_generation(self, client, cache):
        r = client.post("/admin/volunteers/", json={"email": "j@example.org", "name": "Jane"})
        vid = r.get_json()["data"]["id"]
        cache.set("vol_log:l1", json.dumps({"volunteer_id": vid, "status": "completed", "hours": 10.24, "id": "l1"}))
        cache.set("vol_log:l2", json.dumps({"volunteer_id": vid, "status": "completed", "hours": 2.0, "id": "l2"}))
        cache.set("vol_log:index", ["l1", "l2"])
        r = client.post(f"/admin/volunteers/{vid}/certificate")
        assert r.status_code == 200
        cert = r.get_json()["data"]
        assert cert["volunteer_id"] == vid
        assert cert["volunteer_name"] == "Jane"
        assert cert["total_hours"] == 12.2
        assert cert["status"] == "valid"
        assert cert["organization"] == "SOGo Foundation"
        assert cert["signed_by"] == "Volunteer Coordinator"
        assert "certificate_id" in cert
        assert "issued_at" in cert and "year" in cert
        # certificate id appended to volunteer record
        vol = json.loads(cache.store[f"vol:{vid}"])
        assert cert["certificate_id"] in vol["certificates"]


# ─────────────────────────────────────────────────────────────────────────────
# _compute_shift_conflicts (unit)
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeShiftConflicts:
    def test_detects_overlap(self, cache):
        from app.api.v1.admin.ApiVolunteerScheduling import _compute_shift_conflicts
        cache.set("vol_shift:s1", json.dumps({
            "id": "s1", "volunteer_id": "v1", "status": "assigned",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:s2", json.dumps({
            "id": "s2", "volunteer_id": "v1", "status": "completed",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:s3", json.dumps({
            "id": "s3", "volunteer_id": "other", "status": "assigned",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:index", ["s1", "s2", "s3"])
        with patch("app.api.v1.admin.ApiVolunteerScheduling.sogo_cache", return_value=cache):
            assert _compute_shift_conflicts("v1", 1500, 2500) == ["s1"]

    def test_no_conflict_when_non_overlapping(self, cache):
        from app.api.v1.admin.ApiVolunteerScheduling import _compute_shift_conflicts
        cache.set("vol_shift:s1", json.dumps({
            "id": "s1", "volunteer_id": "v1", "status": "assigned",
            "start_time": 1000, "end_time": 2000}))
        cache.set("vol_shift:index", ["s1"])
        with patch("app.api.v1.admin.ApiVolunteerScheduling.sogo_cache", return_value=cache):
            assert _compute_shift_conflicts("v1", 2000, 3000) == []
            assert _compute_shift_conflicts("v1", 500, 1000) == []


# ─────────────────────────────────────────────────────────────────────────────
# _generate_certificate (unit)
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateCertificate:
    def test_fields(self):
        from app.api.v1.admin.ApiVolunteerScheduling import _generate_certificate
        cert = _generate_certificate("v123", 42.55, "Kim")
        assert cert["volunteer_id"] == "v123"
        assert cert["volunteer_name"] == "Kim"
        assert cert["total_hours"] == 42.5
        assert cert["year"] == int(time.strftime("%Y"))
        assert cert["organization"] == "SOGo Foundation"
        assert cert["signed_by"] == "Volunteer Coordinator"
        assert cert["status"] == "valid"
