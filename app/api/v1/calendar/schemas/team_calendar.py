"""Schemas for Team Calendar endpoints (spec: team-calendars)."""

from marshmallow import Schema, fields, validate

from app.utils.api.ApiBaseResponse import ApiBaseResponse

SHARE_LEVEL_VALUES = ("view_date_time", "view_all", "respond", "modify_if_org", "modify")


class TeamCalendarCreateSchema(Schema):
    """Request body for creating a team calendar."""

    name        = fields.String(required=True, metadata={"example": "Engineering Team"})
    color       = fields.String(load_default=None, allow_none=True, metadata={"example": "#4a9eff"})
    description = fields.String(load_default=None, allow_none=True, metadata={"example": "Shared engineering calendar"})
    timezone    = fields.String(load_default="UTC", metadata={"example": "Europe/Paris"})


class TeamCalendarUpdateSchema(Schema):
    """Request body for updating a team calendar (all fields optional)."""

    name        = fields.String(load_default=None, allow_none=True)
    color       = fields.String(load_default=None, allow_none=True)
    description = fields.String(load_default=None, allow_none=True)
    timezone    = fields.String(load_default=None, allow_none=True)


class TeamCalendarMemberSchema(Schema):
    """A team calendar member (share entry)."""

    user_uid       = fields.String(metadata={"example": "alice@example.org"})
    share_level    = fields.String(metadata={"example": "view_all"})
    can_create     = fields.Boolean()
    can_delete     = fields.Boolean()


class TeamCalendarMemberListDataSchema(Schema):
    """Data wrapper for a list of members."""

    members     = fields.List(fields.Nested(TeamCalendarMemberSchema))
    total_count = fields.Integer()


class TeamCalendarMemberListResponseSchema(ApiBaseResponse):
    """Response for GET /calendars/teams/{team_id}/members."""

    data = fields.Nested(TeamCalendarMemberListDataSchema, allow_none=True)


class TeamCalendarAddMemberSchema(Schema):
    """Request body for adding a member or sending an invitation."""

    user_uid    = fields.String(required=True, metadata={"example": "alice@example.org"})
    share_level = fields.String(load_default="view_all", validate=validate.OneOf(SHARE_LEVEL_VALUES),
                                metadata={"example": "view_all"})


class TeamCalendarUpdateMemberSchema(Schema):
    """Request body for updating a member's permissions."""

    share_level = fields.String(required=True, validate=validate.OneOf(SHARE_LEVEL_VALUES),
                                metadata={"example": "modify"})


class TeamCalendarMemberResponseSchema(ApiBaseResponse):
    """Response for a single member operation."""

    data = fields.Nested(TeamCalendarMemberSchema, allow_none=True)


class TeamCalendarInviteSchema(Schema):
    """A calendar invitation."""

    id           = fields.String(metadata={"example": "abc123"})
    calendar_key = fields.String(metadata={"example": "cal_xyz"})
    user_uid     = fields.String(metadata={"example": "alice@example.org"})
    invited_by   = fields.String(metadata={"example": "bob@example.org"})
    status       = fields.String(metadata={"example": "pending"})
    share_level  = fields.String(metadata={"example": "view_all"})
    created_at   = fields.DateTime(allow_none=True)


class TeamCalendarInviteListDataSchema(Schema):
    """Data wrapper for a list of invitations."""

    invites     = fields.List(fields.Nested(TeamCalendarInviteSchema))
    total_count = fields.Integer()


class TeamCalendarInviteListResponseSchema(ApiBaseResponse):
    """Response for GET /calendars/teams/invites."""

    data = fields.Nested(TeamCalendarInviteListDataSchema, allow_none=True)


class TeamCalendarInviteResponseSchema(ApiBaseResponse):
    """Response for single-invite operations (get/accept/reject/cancel/resend)."""

    data = fields.Nested(TeamCalendarInviteSchema, allow_none=True)


class TeamCalendarInviteAcceptResponseSchema(ApiBaseResponse):
    """Response for POST /calendars/teams/invites/{invite_id}/accept — returns the membership."""

    data = fields.Nested(TeamCalendarMemberSchema, allow_none=True)
