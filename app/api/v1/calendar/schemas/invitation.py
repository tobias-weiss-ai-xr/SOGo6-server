"""Schemas for the calendar invitation / attendee / RSVP endpoints (BACKEND-GAPS F1).

Covers the three "Expose Invitation Endpoints" payloads:

* ``POST /calendars/<key>/events/<event_key>/invite``  -> :class:`InviteResponseSchema`
* ``GET  /calendars/<key>/events/<event_key>/attendees`` -> :class:`AttendeeListResponseSchema`
* ``PUT  /calendars/<key>/events/<event_key>/attendees/<attendee_id>``
                                                          -> :class:`RsvpUpdateSchema` (body)
                                                          / ``CalendarEventResponseSchema`` (response)

Attendees are modelled after the ``AttendeeSchema`` used for event create/update so the
whole calendar API agrees on the RFC 5545 ATTENDEE shape.
"""
from __future__ import annotations

from marshmallow import Schema, fields, validate

from app.module.calendar.model.enums.AttendeeStatus import AttendeeStatus
from app.utils.api.ApiBaseResponse import ApiBaseResponse

from .components import AttendeeSchema

# RFC 5545 §3.2.12 PARTSTAT literals currently modelled by AttendeeStatus.
_PARTSTAT_VALUES = [status.value for status in AttendeeStatus]


class RsvpUpdateSchema(Schema):
    """Request body for updating a single attendee's RSVP status (RFC 5545 PARTSTAT)."""

    status = fields.String(
        required=True,
        validate=validate.OneOf(_PARTSTAT_VALUES),
        metadata={"description": "needs-action | accepted | declined | tentative | delegated"},
    )


class AttendeeListDataSchema(Schema):
    """Data payload of ``GET .../events/<event_key>/attendees``."""

    attendees = fields.List(fields.Nested(AttendeeSchema), metadata={"description": "The event attendees."})
    total_count = fields.Integer(metadata={"description": "Number of attendees listed."})


class AttendeeListResponseSchema(ApiBaseResponse):
    """Response schema for ``GET .../events/<event_key>/attendees``."""

    data = fields.Nested(AttendeeListDataSchema, allow_none=True)


class InviteDataSchema(Schema):
    """Data payload of ``POST .../events/<event_key>/invite``."""

    event_key = fields.String(metadata={"description": "Opaque key of the invited event."})
    invited = fields.List(
        fields.String(),
        metadata={"description": "Attendee email addresses the invitation was delivered to (best-effort)."},
    )
    total_attendees = fields.Integer(metadata={"description": "Total number of attendees on the event."})


class InviteResponseSchema(ApiBaseResponse):
    """Response schema for ``POST .../events/<event_key>/invite``."""

    data = fields.Nested(InviteDataSchema, allow_none=True)
