# Tier 1 Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | tier1-implementation |
| **Title** | Tier 1 Core Experience Features |
| **Status** | In Progress |
| **Priority** | High |
| **Type** | Feature Implementation |
| **Created** | 2026-08-06 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 1 Core Experience |
| **Spec** | See ROADMAP Tier 1 |

---

## Overview

Tier 1 — Core Experience: features visible daily to all users (UX parity with
modern groupware). Many Tier 1 features already existed in the codebase when
Tier 0 completed (Conversation View, Schedule Send, Email Snooze, Push
Notifications, Keyboard Shortcuts, PGP, Follow-Up Flags, Quick Reply Templates,
Drag-and-Drop). This tracker covers the remaining work.

## Progress

| # | Feature | Backend | Frontend | Tests | Status |
|---|---------|---------|----------|-------|--------|
| 9 | Conversation View | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 10 | Calendar Subscriptions | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 11 | Working Hours / Location | ❌ | ❌ | ❌ | Not Started |
| 12 | **Undo Send** | ✅ | ✅ | ✅ | **✅ COMPLETE** |
| 13 | Schedule Send | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 14 | Email Snooze | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 15 | Push Notifications | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 16 | Global Quick Search (Cmd+K) | ❌ | ❌ | ❌ | Not Started |
| 17 | PWA / Mobile Web | ❌ | ❌ | ❌ | Not Started |
| 18 | Keyboard Shortcuts | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 19 | PGP E2E Encryption | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 20 | Follow-Up Flags | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 21 | Quick Reply Templates | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 22 | Drag-and-Drop Attachments | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |

## Task Log

### 2026-08-06 — Undo Send COMPLETE (Tier 1 #12)

- **Backend** (`sogo6-server`): `UndoSendJob.py` delivers pending emails after the
  grace period (was missing entirely — emails would never send). `send_mail` now
  enqueues `UndoSendRequest` with `eta`, stores the user session + outgoing login
  in the pending payload, and falls back to immediate send if enqueue fails.
- **Frontend** (`sogo6-ui`): `cancelPendingSend` RTK mutation + Undo toast in the
  compose send flow (keeps the draft open during the grace period).
- **Tests**: backend 873 passed (6 new agent tests, updated interface tests);
  frontend mails suite 1423 passed (3 new hook tests).
- **Docs**: `undo-send.change.md` + `UNDO_SEND_IMPLEMENTATION_SUMMARY.md`.
