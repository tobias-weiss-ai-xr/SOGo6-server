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
| 11 | **Working Hours / Location** | ✅ | ✅ | ✅ | **✅ COMPLETE** |
| 12 | **Undo Send** | ✅ | ✅ | ✅ | **✅ COMPLETE** |
| 13 | Schedule Send | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 14 | Email Snooze | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 15 | Push Notifications | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 16 | **Global Quick Search (Cmd+K)** | ✅ | ✅ | ✅ | **✅ COMPLETE** |
| 17 | PWA / Mobile Web | ❌ | ❌ | ❌ | Not Started |
| 18 | Keyboard Shortcuts | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 19 | PGP E2E Encryption | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 20 | Follow-Up Flags | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 21 | Quick Reply Templates | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |
| 22 | Drag-and-Drop Attachments | ✅ | ✅ | ✅ | ✅ COMPLETE (pre-existing) |

## Task Log

### 2026-08-06 — Global Quick Search (Cmd+K) COMPLETE (Tier 1 #16)

- **Backend** (`sogo6-server`): new `GET /search/global?q=` user API endpoint
  (`ApiGlobalSearch.py` + `InterfaceApiGlobalSearch`) aggregating **contacts**
  (transverse across all address books), **calendar events** (title/description
  search in a 1-year rolling window) and **directory users** (LDAP). Each
  section is isolated — one failing source never breaks the others.
- **Frontend** (`sogo6-ui`): `GlobalQuickSearch` (existing Cmd+K palette) now
  calls `useGlobalSearchQuery` (RTK, debounced 200 ms) and renders grouped
  results (Contacts / Calendar events / Users) with navigation actions, a
  loading spinner and empty states. New `search/*` i18n keys.
- **Tests**: backend 892 passed (4 interface + 9 structural tests); frontend
  search suite 10 passed + layout test updated (mock of the search store).
- **Docs**: `global-quick-search.change.md` + implementation summary.

### 2026-08-06 — Working Hours / Location COMPLETE (Tier 1 #11)

- **Backend** (`sogo6-server`): added `SOGO_U_DEFAULT_LOCATION` to
  `UserCalendarGeneralSettings` (default meeting location). `SOGO_U_WORKDAY_START_TIME` /
  `SOGO_U_WORKDAY_END_TIME` / `SOGO_U_BUSY_OFF_HOURS` / `SOGO_U_NON_WORKING_WEEKDAYS` already
  existed and were already honored by `FreeBusyEngine` via `FreeBusyPrefs`.
- **Frontend** (`sogo6-ui`): added `nonWorkingWeekdays` multi-select + `defaultLocation` input
  to the Calendar → General settings form; new fields wired through types, zod schema,
  `calendar-utils` mapping, fakeApi, and i18n.
- **Tests**: backend 879 passed (6 new `UserCalendarGeneralSettings` tests); frontend
  1566 passed across calendar/user-settings/fakeApi.

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
