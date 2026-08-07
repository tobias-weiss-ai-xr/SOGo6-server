"""Volunteer Scheduling (#71) — non-profit market.

Shift management, availability tracking, hour logging, 
no-show tracking, and certificate generation.
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timedelta

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Volunteer Scheduling", __name__, url_prefix="/admin/volunteers")

_VOL_PFX = "vol:"
_SHIFT_PFX = "vol_shift:"
_LOG_PFX = "vol_log:"


def _generate_certificate(volunteer_id: str, hours: float, volunteer_name: str) -> dict:
    """Generate a volunteer service certificate."""
    return {
        "certificate_id": secrets.token_hex(12),
        "volunteer_id": volunteer_id,
        "volunteer_name": volunteer_name,
        "total_hours": round(hours, 1),
        "year": int(time.strftime("%Y")),
        "issued_at": time.time(),
        "organization": "SOGo Foundation",
        "signed_by": "Volunteer Coordinator",
        "status": "valid",
    }


def _compute_shift_conflicts(vol_id: str, shift_start: float, shift_end: float) -> list[str]:
    """Check if volunteer has overlapping shifts."""
    cache = sogo_cache()
    idx = list(cache.get(f"{_SHIFT_PFX}index", list) or [])
    conflicts = []
    for sid in idx:
        raw = cache.get(f"{_SHIFT_PFX}{sid}", str)
        if raw:
            s = json.loads(raw)
            if s.get("volunteer_id") == vol_id and s.get("status") == "assigned":
                if shift_start < s["end_time"] and shift_end > s["start_time"]:
                    conflicts.append(sid)
    return conflicts


@blp.route("/")
class VolunteerList(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_VOL_PFX}index", list) or [])
        volunteers = []
        for vid in idx:
            raw = cache.get(f"{_VOL_PFX}{vid}", str)
            if raw:
                v = json.loads(raw)
                # Compute total hours from logs
                log_idx = list(cache.get(f"{_LOG_PFX}index", list) or [])
                total_hours = 0.0
                for lid in log_idx:
                    lraw = cache.get(f"{_LOG_PFX}{lid}", str)
                    if lraw:
                        l = json.loads(lraw)
                        if l.get("volunteer_id") == vid and l.get("status") == "completed":
                            total_hours += l.get("hours", 0)
                v["total_hours"] = round(total_hours, 1)
                volunteers.append(v)
        volunteers.sort(key=lambda v: v.get("total_hours", 0), reverse=True)
        return create_api_base_response(data=volunteers)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        email = (body.get("email") or "").strip().lower()
        name = body.get("name", "")
        if not email or not name:
            return create_api_base_response(error_code="E000003", error_msg="email and name required", success=False)
        cache = sogo_cache()
        vid = secrets.token_hex(8)
        vol = {
            "id": vid,
            "email": email,
            "name": name,
            "phone": body.get("phone", ""),
            "skills": body.get("skills", []),
            "availability": body.get("availability", {
                "monday": [], "tuesday": [], "wednesday": [],
                "thursday": [], "friday": [], "saturday": [], "sunday": [],
            }),
            "max_hours_per_week": body.get("max_hours_per_week", 20),
            "no_show_count": 0,
            "total_hours": 0,
            "status": "active",  # active, inactive, suspended
            "certificates": [],
            "created_at": time.time(),
        }
        cache.set(f"{_VOL_PFX}{vid}", json.dumps(vol), ttl=86400 * 365)
        idx = list(cache.get(f"{_VOL_PFX}index", list) or [])
        idx.append(vid)
        cache.set(f"{_VOL_PFX}index", idx, ttl=86400 * 365)
        logger_api.info("Volunteer registered: %s (%s)", name, email)
        return create_api_base_response(data=vol)


@blp.route("/<vol_id>")
class VolunteerDetail(MethodView):
    def get(self, vol_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_VOL_PFX}{vol_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Volunteer not found", success=False)
        vol = json.loads(raw)
        # Get shifts
        s_idx = list(cache.get(f"{_SHIFT_PFX}index", list) or [])
        shifts = [json.loads(cache.get(f"{_SHIFT_PFX}{sid}", str)) for sid in s_idx
                  if cache.get(f"{_SHIFT_PFX}{sid}", str) and json.loads(cache.get(f"{_SHIFT_PFX}{sid}", str)).get("volunteer_id") == vol_id]
        shifts.sort(key=lambda x: x.get("start_time", 0))
        vol["shifts"] = shifts
        return create_api_base_response(data=vol)


@blp.route("/shifts")
class ShiftList(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_SHIFT_PFX}index", list) or [])
        shifts = []
        for sid in idx:
            raw = cache.get(f"{_SHIFT_PFX}{sid}", str)
            if raw:
                shifts.append(json.loads(raw))
        shifts.sort(key=lambda x: x.get("start_time", 0))
        return create_api_base_response(data=shifts)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        vol_id = body.get("volunteer_id", "")
        start_time = body.get("start_time", 0)
        end_time = body.get("end_time", 0)
        if not vol_id or not start_time or not end_time:
            return create_api_base_response(error_code="E000003", error_msg="volunteer_id, start_time, end_time required", success=False)
        if end_time <= start_time:
            return create_api_base_response(error_code="E000006", error_msg="end_time must be after start_time", success=False)
        cache = sogo_cache()
        # Check conflicts
        conflicts = _compute_shift_conflicts(vol_id, start_time, end_time)
        if conflicts:
            return create_api_base_response(error_code="E000007", error_msg=f"Conflicts with {len(conflicts)} existing shifts", success=False, data={"conflicts": conflicts})
        sid = secrets.token_hex(10)
        hours = (end_time - start_time) / 3600.0
        shift = {
            "id": sid,
            "volunteer_id": vol_id,
            "start_time": start_time,
            "end_time": end_time,
            "hours": round(hours, 1),
            "location": body.get("location", ""),
            "task": body.get("task", "general"),
            "status": body.get("status", "scheduled"),  # scheduled, assigned, in_progress, completed, no_show
            "notes": body.get("notes", ""),
            "created_at": time.time(),
        }
        cache.set(f"{_SHIFT_PFX}{sid}", json.dumps(shift), ttl=86400 * 365)
        s_idx = list(cache.get(f"{_SHIFT_PFX}index", list) or [])
        s_idx.append(sid)
        cache.set(f"{_SHIFT_PFX}index", s_idx, ttl=86400 * 365)
        return create_api_base_response(data=shift)


@blp.route("/shifts/<shift_id>/checkin")
class ShiftCheckin(MethodView):
    def post(self, shift_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_SHIFT_PFX}{shift_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Shift not found", success=False)
        shift = json.loads(raw)
        shift["status"] = "in_progress"
        shift["checkin_time"] = time.time()
        cache.set(f"{_SHIFT_PFX}{shift_id}", json.dumps(shift), ttl=86400 * 365)
        return create_api_base_response(data=shift)


@blp.route("/shifts/<shift_id>/checkout")
class ShiftCheckout(MethodView):
    def post(self, shift_id: str) -> ResponseReturnValue:
        body = request.get_json(force=True)
        cache = sogo_cache()
        raw = cache.get(f"{_SHIFT_PFX}{shift_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Shift not found", success=False)
        shift = json.loads(raw)
        actual_end = time.time()
        actual_hours = round((actual_end - (shift.get("checkin_time") or shift["start_time"])) / 3600.0, 1)
        shift["status"] = "completed"
        shift["checkout_time"] = actual_end
        shift["actual_hours"] = actual_hours
        cache.set(f"{_SHIFT_PFX}{shift_id}", json.dumps(shift), ttl=86400 * 365)
        # Log hours
        lid = secrets.token_hex(10)
        log = {
            "id": lid,
            "volunteer_id": shift["volunteer_id"],
            "shift_id": shift_id,
            "hours": actual_hours,
            "status": "completed",
            "date": actual_end,
            "notes": body.get("notes", ""),
        }
        cache.set(f"{_LOG_PFX}{lid}", json.dumps(log), ttl=86400 * 365)
        log_idx = list(cache.get(f"{_LOG_PFX}index", list) or [])
        log_idx.append(lid)
        cache.set(f"{_LOG_PFX}index", log_idx, ttl=86400 * 365)
        return create_api_base_response(data=log)


@blp.route("/<vol_id>/certificate")
class VolunteerCertificate(MethodView):
    def post(self, vol_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_VOL_PFX}{vol_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Volunteer not found", success=False)
        vol = json.loads(raw)
        # Compute total hours
        log_idx = list(cache.get(f"{_LOG_PFX}index", list) or [])
        total_hours = 0.0
        for lid in log_idx:
            lraw = cache.get(f"{_LOG_PFX}{lid}", str)
            if lraw:
                l = json.loads(lraw)
                if l.get("volunteer_id") == vol_id and l.get("status") == "completed":
                    total_hours += l.get("hours", 0)
        cert = _generate_certificate(vol_id, total_hours, vol["name"])
        vol["certificates"].append(cert["certificate_id"])
        cache.set(f"{_VOL_PFX}{vol_id}", json.dumps(vol), ttl=86400 * 365)
        return create_api_base_response(data=cert)
