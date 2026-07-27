"""
Schema for calendar administration API
"""

from marshmallow import Schema, fields


class CalendarCleanPostSchema(Schema):
    """
    Request schema for triggering a calendar clean (purge soft-deleted events/reminders).
    At least one of user_uid or calendar_key must be provided.
    """
    user_uid = fields.String(
        metadata={"description": "Clean all calendars owned by this user."},
    )
    calendar_key = fields.String(
        metadata={"description": "Clean a specific calendar by its key."},
    )


class CalendarCleanResponseSchema(Schema):
    """
    Response schema for a calendar clean operation.
    """
    purged_rows = fields.Integer(
        dump_default=0,
        metadata={"description": "Total number of soft-deleted rows physically removed."},
    )
