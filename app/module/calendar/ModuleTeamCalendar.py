from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.module.calendar.model.CalCalendar import CalCalendar
from app.module.calendar.model.CalendarInvite import (
    CalendarInvite,
    INVITE_STATUS_PENDING,
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_REJECTED,
    INVITE_STATUS_CANCELLED,
)
from app.module.calendar.model.CalendarShare import CalendarShare
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType
from app.module.calendar.ModuleCalendar import ModuleCalendar
from app.module.calendar.repository.RepositoryCalendarInvite import RepositoryCalendarInvite
from app.module.calendar.repository.RepositoryCalendarShare import RepositoryCalendarShare
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_calendar
from app.utils.maths.sogo_hash import generate_uuid

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.manager.cache.ClientRedis import ClientRedis
    from app.manager.agent.ClientAgent import ClientAgent


class ModuleTeamCalendar:
    """Team calendar service layer.

    Team calendars are regular calendars with ``source_type=team`` and a stable
    owner (``user_uid``). Membership is modelled with the existing calendar share
    repository; pending memberships flow through the calendar invites repository.
    """

    def __init__(
        self, process_settings: ProcessSetting,
        cache: ClientRedis | None = None, agent: ClientAgent | None = None,
    ) -> None:
        self._calendar_module: ModuleCalendar = ModuleCalendar(process_settings, cache=cache, agent=agent)
        self._share_repo: RepositoryCalendarShare = self._calendar_module._share_repo  # reuse connection
        self._invite_repo: RepositoryCalendarInvite = RepositoryCalendarInvite(self._calendar_module._db)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_share_level(value: str | None, default: str = "view_all") -> CalendarShareLevel:
        """Parse a share level string into a CalendarShareLevel (case-insensitive)."""
        raw = (value or default).upper().replace("_", "")
        for member in CalendarShareLevel:
            if member.name.replace("_", "") == raw:
                return member
        return CalendarShareLevel[default.upper()]

    def _require_team_calendar(self, user: User, team_id: str) -> CalCalendar:
        """Load a calendar and verify it is a team calendar the user can access."""
        source = self._calendar_module.get_calendar(user, team_id)
        if source.calendar.source_type != CalendarSourceType.TEAM:
            raise RequestException(error=err.ERROR_CALENDAR_NOT_TEAM)
        return source.calendar

    def _require_owner(self, user: User, team_id: str) -> CalCalendar:
        """Load a team calendar and verify the user is its owner."""
        cal = self._require_team_calendar(user, team_id)
        if cal.user_uid != user.uid:
            raise RequestException(error=err.ERROR_CALENDAR_ACCESS_DENIED)
        return cal

    # ------------------------------------------------------------------ #
    # Team calendar CRUD                                                  #
    # ------------------------------------------------------------------ #

    def list_team_calendars(self, user: User) -> list[CalCalendar]:
        """List team calendars the user owns or is a member of."""
        owned = self._calendar_module.get_all_calendars(user)
        shared_keys = self._share_repo.find_calendar_keys_for_user(user.uid)
        shared = self._calendar_module.get_all_calendars(user, shared_keys=shared_keys) if shared_keys else []
        seen: set[str] = set()
        teams: list[CalCalendar] = []
        for cal in [*owned, *shared]:
            if cal.source_type != CalendarSourceType.TEAM:
                continue
            if cal.key in seen:
                continue
            seen.add(cal.key)
            teams.append(cal)
        return teams

    def get_team_calendar(self, user: User, team_id: str) -> CalCalendar:
        """Get a single team calendar the user can access."""
        return self._require_team_calendar(user, team_id)

    def create_team_calendar(self, user: User, name: str, color: str | None = None,
                             description: str | None = None, timezone: str = "UTC") -> CalCalendar:
        """Create a new team calendar owned by the current user."""
        cal = CalCalendar(
            user_uid=user.uid,
            name=name,
            color=color,
            description=description,
            timezone=timezone,
            source_type=CalendarSourceType.TEAM,
            is_default=False,
        )
        cal.key = generate_uuid()
        cal.ctag = 0
        return self._calendar_module.create_calendar(user, cal)

    def update_team_calendar(self, user: User, team_id: str, updates: dict[str, Any]) -> CalCalendar:
        """Update a team calendar's metadata (owner only)."""
        cal = self._require_owner(user, team_id)
        cal.apply_update(updates)
        return self._calendar_module.update_calendar(user, team_id, cal)

    def delete_team_calendar(self, user: User, team_id: str) -> None:
        """Delete a team calendar (owner only)."""
        self._require_owner(user, team_id)
        self._calendar_module.delete_calendar(user, team_id)

    # ------------------------------------------------------------------ #
    # Membership                                                          #
    # ------------------------------------------------------------------ #

    def list_members(self, user: User, team_id: str) -> list[CalendarShare]:
        """List members (shares) of a team calendar."""
        self._require_team_calendar(user, team_id)
        return self._share_repo.find_by_calendar_key(team_id)

    def add_member(self, user: User, team_id: str, member_uid: str,
                   share_level: str = "view_all") -> CalendarShare:
        """Add a member directly to a team calendar (owner only)."""
        cal = self._require_owner(user, team_id)
        if member_uid == cal.user_uid:
            raise RequestException(error=err.ERROR_CALENDAR_DUPLICATE)
        existing = self._share_repo.find_by_calendar_and_user(team_id, member_uid)
        if existing is not None:
            raise RequestException(error=err.ERROR_CALENDAR_DUPLICATE)
        level = self._parse_share_level(share_level, "view_all")
        share = CalendarShare(
            calendar_key=team_id,
            user_uid=member_uid,
            public_level=level,
            confidential_level=CalendarShareLevel.VIEW_DATETIME,
            private_level=CalendarShareLevel.NONE,
            can_create=level >= CalendarShareLevel.MODIFY,
            can_delete=level >= CalendarShareLevel.MODIFY,
        )
        return self._share_repo.insert(share)

    def update_member(self, user: User, team_id: str, member_uid: str,
                      share_level: str) -> CalendarShare:
        """Update a member's permission level (owner only)."""
        self._require_owner(user, team_id)
        existing = self._share_repo.find_by_calendar_and_user(team_id, member_uid)
        if existing is None:
            raise RequestException(error=err.ERROR_CALENDAR_MEMBER_NOT_FOUND)
        level = self._parse_share_level(share_level, "view_all")
        existing.public_level = level
        existing.confidential_level = CalendarShareLevel.VIEW_DATETIME
        existing.private_level = CalendarShareLevel.NONE
        existing.can_create = level >= CalendarShareLevel.MODIFY
        existing.can_delete = level >= CalendarShareLevel.MODIFY
        # The repository has no update; delete + re-insert preserves semantics.
        self._share_repo.delete(team_id, member_uid)
        return self._share_repo.insert(existing)

    def remove_member(self, user: User, team_id: str, member_uid: str) -> None:
        """Remove a member from a team calendar (owner only)."""
        self._require_owner(user, team_id)
        self._share_repo.delete(team_id, member_uid)

    # ------------------------------------------------------------------ #
    # Invitations                                                         #
    # ------------------------------------------------------------------ #

    def invite_user(self, user: User, team_id: str, member_uid: str,
                    share_level: str = "view_all") -> CalendarInvite:
        """Send an invitation for a team calendar (owner only)."""
        cal = self._require_owner(user, team_id)
        if member_uid == cal.user_uid:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_ALREADY_EXISTS)
        existing = self._invite_repo.find_by_calendar_and_user(team_id, member_uid)
        if existing is not None and existing.status == INVITE_STATUS_PENDING:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_ALREADY_EXISTS)
        if existing is not None:
            # Reuse the row, flip it back to pending (resend semantics)
            self._invite_repo.update_status(existing.id, INVITE_STATUS_PENDING)
            existing.status = INVITE_STATUS_PENDING
            existing.share_level = self._parse_share_level(share_level, "view_all").name.lower()
            return existing
        invite = CalendarInvite(
            id=generate_uuid(),
            calendar_key=team_id,
            user_uid=member_uid,
            invited_by=user.uid,
            status=INVITE_STATUS_PENDING,
            share_level=self._parse_share_level(share_level, "view_all").name.lower(),
        )
        return self._invite_repo.insert(invite)

    def list_invites(self, user: User) -> list[CalendarInvite]:
        """List pending invitations for the current user."""
        return self._invite_repo.find_pending_for_user(user.uid)

    def get_invite(self, user: User, invite_id: str) -> CalendarInvite:
        """Get an invitation (as the invitee or the inviting owner)."""
        invite = self._invite_repo.find_by_id(invite_id)
        if invite is None:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_NOT_FOUND)
        if invite.user_uid != user.uid and invite.invited_by != user.uid:
            raise RequestException(error=err.ERROR_CALENDAR_ACCESS_DENIED)
        return invite

    def accept_invite(self, user: User, invite_id: str) -> CalendarShare:
        """Accept a pending invitation, creating the membership share."""
        invite = self.get_invite(user, invite_id)
        if invite.user_uid != user.uid:
            raise RequestException(error=err.ERROR_CALENDAR_ACCESS_DENIED)
        if invite.status != INVITE_STATUS_PENDING:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_INVALID_STATUS)
        # Guard: if a share already exists, treat as accepted idempotently.
        existing = self._share_repo.find_by_calendar_and_user(invite.calendar_key, user.uid)
        if existing is None:
            level = self._parse_share_level(invite.share_level, "view_all")
            share = CalendarShare(
                calendar_key=invite.calendar_key,
                user_uid=user.uid,
                public_level=level,
                confidential_level=CalendarShareLevel.VIEW_DATETIME,
                private_level=CalendarShareLevel.NONE,
                can_create=level >= CalendarShareLevel.MODIFY,
                can_delete=level >= CalendarShareLevel.MODIFY,
            )
            existing = self._share_repo.insert(share)
        self._invite_repo.update_status(invite.id, INVITE_STATUS_ACCEPTED)
        return existing

    def reject_invite(self, user: User, invite_id: str) -> CalendarInvite:
        """Reject a pending invitation."""
        invite = self.get_invite(user, invite_id)
        if invite.user_uid != user.uid:
            raise RequestException(error=err.ERROR_CALENDAR_ACCESS_DENIED)
        if invite.status != INVITE_STATUS_PENDING:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_INVALID_STATUS)
        self._invite_repo.update_status(invite.id, INVITE_STATUS_REJECTED)
        invite.status = INVITE_STATUS_REJECTED
        return invite

    def cancel_invite(self, user: User, invite_id: str) -> CalendarInvite:
        """Cancel/revoke an invitation (owner only)."""
        invite = self.get_invite(user, invite_id)
        if invite.invited_by != user.uid:
            raise RequestException(error=err.ERROR_CALENDAR_ACCESS_DENIED)
        if invite.status != INVITE_STATUS_PENDING:
            raise RequestException(error=err.ERROR_CALENDAR_INVITE_INVALID_STATUS)
        self._invite_repo.update_status(invite.id, INVITE_STATUS_CANCELLED)
        invite.status = INVITE_STATUS_CANCELLED
        return invite
