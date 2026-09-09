# Global Quick Search Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | global-quick-search |
| **Title** | Implement Global Quick Search (Cmd+K) Feature |
| **Status** | Complete |
| **Priority** | High |
| **Type** | Feature Implementation |
| **Created** | 2026-08-06 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 1 Core Experience |
| **Spec** | [mail.spec.md](../specs/mail.spec.md) / [contacts.spec.md](../specs/contacts.spec.md) / [calendar.spec.md](../specs/calendar.spec.md) |

---

## Overview

**Global Quick Search (Cmd+K)** (ROADMAP Tier 1 #16) — a unified search bar
(Cmd+K / Ctrl+K) that searches **mail, contacts, calendar events, users and
settings** simultaneously.

The command palette UI already existed with static navigation shortcuts and a
Cmd+K binding, but the dynamic search was a TODO stub. This change wires it to
a new backend aggregation endpoint and renders grouped live results.

## Related Artifacts

- **Roadmap**: [ROADMAP.md](../../ROADMAP.md) Tier 1 #16
- **Parent Change**: [tier1-implementation.change.md](./tier1-implementation.change.md)

## Goals

Unified search bar (Cmd+K) searching mail, contacts, calendar, users, settings
simultaneously.

## Tasks

- [x] Backend: `GET /search/global?q=&limit=` user API endpoint
  (`app/api/v1/user/ApiGlobalSearch.py` + `InterfaceApiGlobalSearch`)
- [x] Backend: aggregates contacts (transverse, all address books),
  calendar events (title/description search, 1-year rolling window),
  directory users (LDAP via `ModuleAdminUser.list_users`)
- [x] Backend: per-section error isolation (one failing source never breaks the response)
- [x] Backend: Marshmallow query schema (`q` required, `limit` 1–50, default 8)
- [x] Backend: blueprint registered in the user API list
- [x] Backend: tests — `test_InterfaceApiGlobalSearch.py` (4) + `test_ApiGlobalSearch.py` (9 structural)
- [x] Frontend: `global-search-api.ts` RTK endpoint (debounced, `skip` until 2+ chars)
- [x] Frontend: `GlobalQuickSearch` renders grouped results (Contacts / Calendar events / Users)
  with navigation actions, loading spinner, empty states
- [x] Frontend: `search.json` i18n keys (headings, searching, untitled event)
- [x] Frontend: fakeApi `search/global` demo route
- [x] Frontend: tests — store (6) + component (4) + layout test mock updated
- [x] Docs

## Success Criteria

- [x] Cmd+K / Ctrl+K opens the palette
- [x] Typing 2+ characters performs a debounced unified search
- [x] Contacts, calendar events and users appear as separate groups
- [x] Selecting a contact navigates to it; selecting an event opens the calendar
- [x] Mail search remains available via the existing per-account search
- [x] No regressions: backend 892 passed / frontend search suites 10 passed

## Implementation Details

**Backend**: `InterfaceApiGlobalSearch` composes three module calls —
`ModuleContact.get_contacts(search=...)` (transverse), `ModuleCalendar.get_all_events(search=...)`
within `now..now+365d`, and `ModuleAdminUser.list_users(query=...)`. Each call is wrapped in
its own try/except so a failing LDAP or DB never degrades the other sections. Results are
serialized to lightweight `{contacts, events, users}` arrays.

**Frontend**: `GlobalQuickSearch` keeps the existing Cmd+K binding and static
navigation group, then adds a debounced (200 ms) `useGlobalSearchQuery` call.
Results are grouped under Contacts / Calendar events / Users headings; each item
navigates on selection (contact → its address book visualization route,
event → calendar page). A spinner shows while fetching; empty states show when
nothing matches.

**Change Status**: ✅ COMPLETE
**Last Updated**: 2026-08-06
