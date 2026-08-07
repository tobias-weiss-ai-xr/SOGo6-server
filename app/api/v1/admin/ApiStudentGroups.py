"""Student Group Management (#67) — education market.

Batch operations on student groups: bulk-create, enroll/drop, 
course-specific mailing lists, faculty-student role management.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Student Group Management", __name__, url_prefix="/admin/student-groups")

_GRP_PFX = "stu_grp:"
_MBR_PFX = "stu_mbr:"


class GroupCreateSchema(Schema):
    name = fields.String(required=True)
    course_code = fields.String(load_default="")
    semester = fields.String(load_default="")
    academic_year = fields.String(load_default="2024")
    max_students = fields.Integer(load_default=100)
    faculty_email = fields.String(load_default="")


class MemberBatchSchema(Schema):
    group_id = fields.String(required=True)
    emails = fields.List(fields.Email(), required=True)
    role = fields.String(load_default="student")  # student, ta, faculty


class MemberRemoveSchema(Schema):
    group_id = fields.String(required=True)
    emails = fields.List(fields.Email(), required=True)


def _groups_for_faculty(faculty_email: str) -> list[dict]:
    """Return groups where given faculty is assigned."""
    cache = sogo_cache()
    idx = list(cache.get(f"{_GRP_PFX}index", list) or [])
    groups = []
    for gid in idx:
        raw = cache.get(f"{_GRP_PFX}{gid}", str)
        if raw:
            g = json.loads(raw)
            if g.get("faculty_email") == faculty_email:
                groups.append(g)
    return groups


def _check_duplicate(group_id: str, email: str) -> bool:
    cache = sogo_cache()
    mbr_key = f"{_MBR_PFX}{group_id}"
    existing = set(cache.get(mbr_key, set) or set())
    return email in existing


@blp.route("/")
class StudentGroupList(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_GRP_PFX}index", list) or [])
        groups = []
        for gid in idx:
            raw = cache.get(f"{_GRP_PFX}{gid}", str)
            if raw:
                g = json.loads(raw)
                mbr_key = f"{_MBR_PFX}{gid}"
                members = set(cache.get(mbr_key, set) or set())
                g["member_count"] = len(members)
                g["members"] = list(members)
                groups.append(g)
        return create_api_base_response(data=groups)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        name = body.get("name", "").strip()
        if not name:
            return create_api_base_response(error_code="E000001", error_msg="Group name required", success=False)
        cache = sogo_cache()
        gid = secrets.token_hex(8)
        group = {
            "id": gid,
            "name": name,
            "course_code": body.get("course_code", ""),
            "semester": body.get("semester", ""),
            "academic_year": body.get("academic_year", "2024"),
            "max_students": body.get("max_students", 100),
            "faculty_email": body.get("faculty_email", ""),
            "mailing_list": f"{name.lower().replace(' ', '-').replace('_', '-')}@students.local",
            "created_at": time.time(),
        }
        cache.set(f"{_GRP_PFX}{gid}", json.dumps(group), ttl=86400 * 365)
        idx = list(cache.get(f"{_GRP_PFX}index", list) or [])
        idx.append(gid)
        cache.set(f"{_GRP_PFX}index", idx, ttl=86400 * 365)
        logger_api.info("Student group created: %s (%s)", name, gid)
        return create_api_base_response(data=group)


@blp.route("/<group_id>")
class StudentGroupDetail(MethodView):
    def get(self, group_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_GRP_PFX}{group_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Group not found", success=False)
        g = json.loads(raw)
        mbr_key = f"{_MBR_PFX}{group_id}"
        members = set(cache.get(mbr_key, set) or set())
        g["members"] = list(members)
        g["member_count"] = len(members)
        return create_api_base_response(data=g)

    def delete(self, group_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        cache.delete(f"{_GRP_PFX}{group_id}")
        cache.delete(f"{_MBR_PFX}{group_id}")
        idx = list(cache.get(f"{_GRP_PFX}index", list) or [])
        idx = [g for g in idx if g != group_id]
        cache.set(f"{_GRP_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data={"deleted": group_id})


@blp.route("/enroll")
class StudentGroupEnroll(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        group_id = body.get("group_id", "")
        emails = body.get("emails", [])
        role = body.get("role", "student")
        if not group_id or not emails:
            return create_api_base_response(error_code="E000003", error_msg="group_id and emails required", success=False)
        cache = sogo_cache()
        raw = cache.get(f"{_GRP_PFX}{group_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Group not found", success=False)
        group = json.loads(raw)
        mbr_key = f"{_MBR_PFX}{group_id}"
        members = set(cache.get(mbr_key, set) or set())
        added = []
        for email in emails:
            if email not in members:
                members.add(email)
                added.append(email)
        cache.set(mbr_key, members, ttl=86400 * 365)
        logger_api.info("Enrolled %d students in group %s (role=%s)", len(added), group["name"], role)
        return create_api_base_response(data={"added": added, "total": len(members)})


@blp.route("/drop")
class StudentGroupDrop(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        group_id = body.get("group_id", "")
        emails = body.get("emails", [])
        if not group_id or not emails:
            return create_api_base_response(error_code="E000003", error_msg="group_id and emails required", success=False)
        cache = sogo_cache()
        mbr_key = f"{_MBR_PFX}{group_id}"
        members = set(cache.get(mbr_key, set) or set())
        removed = [e for e in emails if e in members]
        for e in removed:
            members.discard(e)
        cache.set(mbr_key, members, ttl=86400 * 365)
        return create_api_base_response(data={"removed": removed, "total": len(members)})
