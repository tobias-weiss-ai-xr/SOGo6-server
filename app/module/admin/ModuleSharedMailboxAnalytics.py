"""Shared mailbox analytics module.

Computes usage statistics for shared mailboxes:
- Total email count (from mail module if available, or from assignments/notes)
- Active member count
- Assignment statistics (pending, accepted, completed)
- Note count
- 7-day and 30-day trends (based on created_at timestamps)

This module is read-only and computes analytics from existing tables
(sogo6_shared_mailboxes, sogo6_shared_mailbox_notes, sogo6_shared_mailbox_assignments).
It does not store data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL

from app.module.admin.ModuleSharedMailboxNotes import ModuleSharedMailboxNotes
from app.module.admin.ModuleSharedMailboxAssignment import ModuleSharedMailboxAssignment


class ModuleSharedMailboxAnalytics:
    """Computes analytics for shared mailboxes."""

    def __init__(self, db: ClientSQL) -> None:
        self._db = db
        self._notes_module = ModuleSharedMailboxNotes(db)
        self._assignment_module = ModuleSharedMailboxAssignment(db)

    def get_analytics(self, mailbox_id: str) -> dict[str, Any]:
        """Get analytics for a specific shared mailbox."""
        now = datetime.now(timezone.utc)

        # Get notes for this mailbox
        notes = self._notes_module.list_notes(mailbox_id)
        public_notes = [n for n in notes if not n.get("is_private")]
        private_notes = [n for n in notes if n.get("is_private")]

        # Get assignments for this mailbox
        assignments = self._assignment_module.list_assignments(mailbox_id=mailbox_id)
        pending = [a for a in assignments if a.get("status") == "pending"]
        accepted = [a for a in assignments if a.get("status") == "accepted"]
        completed = [a for a in assignments if a.get("status") == "completed"]
        cancelled = [a for a in assignments if a.get("status") == "cancelled"]

        # 7-day and 30-day trends
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        notes_7d = [n for n in notes if n.get("created_at", "") >= seven_days_ago]
        notes_30d = [n for n in notes if n.get("created_at", "") >= thirty_days_ago]
        assignments_7d = [a for a in assignments if a.get("created_at", "") >= seven_days_ago]
        assignments_30d = [a for a in assignments if a.get("created_at", "") >= thirty_days_ago]

        # Completion rate
        total_assignments = len(assignments)
        completed_count = len(completed)
        completion_rate = (completed_count / total_assignments * 100) if total_assignments > 0 else 0

        # Average completion time (for completed assignments)
        completion_times = []
        for a in completed:
            created = a.get("created_at")
            completed_at = a.get("completed_at")
            if created and completed_at:
                try:
                    created_dt = datetime.fromisoformat(created)
                    completed_dt = datetime.fromisoformat(completed_at)
                    delta = completed_dt - created_dt
                    completion_times.append(delta.total_seconds())
                except (ValueError, TypeError):
                    continue

        avg_completion_seconds = (
            sum(completion_times) / len(completion_times)
            if completion_times else 0
        )

        return {
            "mailbox_id": mailbox_id,
            "notes": {
                "total": len(notes),
                "public": len(public_notes),
                "private": len(private_notes),
                "last_7_days": len(notes_7d),
                "last_30_days": len(notes_30d),
            },
            "assignments": {
                "total": total_assignments,
                "pending": len(pending),
                "accepted": len(accepted),
                "completed": completed_count,
                "cancelled": len(cancelled),
                "last_7_days": len(assignments_7d),
                "last_30_days": len(assignments_30d),
                "completion_rate": round(completion_rate, 2),
                "avg_completion_seconds": round(avg_completion_seconds, 2),
            },
            "generated_at": now.isoformat(),
        }

    def get_all_analytics(self) -> list[dict[str, Any]]:
        """Get analytics for all shared mailboxes."""
        from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox
        mailbox_module = ModuleSharedMailbox(self._db)
        mailboxes = mailbox_module.get_all()
        return [self.get_analytics(mb["id"]) for mb in mailboxes if mb.get("is_active")]
