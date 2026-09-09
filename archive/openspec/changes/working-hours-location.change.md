# Working Hours / Location Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | working-hours-location |
| **Title** | Implement Working Hours / Location Feature |
| **Status** | Complete |
| **Priority** | High |
| **Type** | Feature Implementation |
| **Created** | 2026-08-06 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 1 Core Experience |
| **Spec** | [calendar.spec.md](../specs/calendar.spec.md) (Working hours, Free/Busy) |

---

## Overview

**Working Hours / Location** (ROADMAP Tier 1 #11) — per-user working hours,
non-working days, and a default meeting location. These preferences permeate
the calendar, scheduling, and free/busy computation.

The backend already defined and honored `SOGO_U_WORKDAY_START_TIME` /
`SOGO_U_WORKDAY_END_TIME` / `SOGO_U_BUSY_OFF_HOURS` /
`SOGO_U_NON_WORKING_WEEKDAYS` (via `FreeBusyPrefs` in `FreeBusyEngine`). This
change adds the **default meeting location** preference and exposes all four
working-hours controls in the Calendar → General settings UI.

## Related Artifacts

- **Specification**: [calendar.spec.md](../specs/calendar.spec.md)
- **Roadmap**: [ROADMAP.md](../../ROADMAP.md) Tier 1 #11
- **Parent Change**: [tier1-implementation.change.md](./tier1-implementation.change.md)

## Goals

See specification: [calendar.spec.md](../specs/calendar.spec.md)

## Tasks

- [x] Backend: `SOGO_U_DEFAULT_LOCATION` added to `UserCalendarGeneralSettings` schema
  (load_default "", dump_default "") — automatically exposed by the preferences API
- [x] Backend: confirm `FreeBusyEngine` honors workday start/end, busy-off-hours,
  and non-working weekdays via `FreeBusyPrefs` (already implemented + tested)
- [x] Backend: tests — `tests/test_config/test_UserCalendarGeneralSettings.py` (6)
- [x] Frontend: `nonWorkingWeekdays` MultiSelect + `defaultLocation` text input added to
  the Calendar → General settings form (`calendar-general-form-core.tsx`)
- [x] Frontend: types (`UserCalendarGeneral` API type + `CalendarGeneralSettings` form type)
  include `SOGO_U_NON_WORKING_WEEKDAYS` / `SOGO_U_DEFAULT_LOCATION`
- [x] Frontend: zod schema updated (`calendar-general-schema.tsx`)
- [x] Frontend: `calendar-utils` mapping (`calendarGeneralToApi` / `apiToCalendarGeneral`)
- [x] Frontend: fakeApi preferences + profile routes include the new fields
- [x] i18n: `nonWorkingWeekdays.*` + `defaultLocation.*` in `user-settings/calendars.json`
- [x] Tests: form-core, calendar-utils, user-preferences-types updated; all 1566 pass

## Success Criteria

- [x] Users can set workday start/end times (existing UI, kept working)
- [x] Users can select which weekdays are non-working (new MultiSelect)
- [x] Users can set a default meeting location pre-filled on new events (new input)
- [x] Free/busy computation honors these preferences (backend, pre-existing + tested)
- [x] Settings persist through the preferences API (schema round-trip tested)
- [x] No regressions: backend 879 passed / frontend 1566 passed

## Implementation Details

**Backend**: `UserCalendarGeneralSettings` gained `SOGO_U_DEFAULT_LOCATION`
(String, default ""). Because the preferences API serializes this schema
directly, the field is immediately readable/writable through
`GET/PUT /user/preferences`. `FreeBusyEngine` (via `FreeBusyPrefs`) already
computes UNAVAILABLE periods outside working hours and on non-working days when
`SOGO_U_BUSY_OFF_HOURS` is enabled.

**Frontend**: the Calendar → General form now renders:
- `nonWorkingWeekdays` — reuses the existing day-of-week `MultiSelect`
  (labels from `calendarDaysShowed.*` i18n keys; values 0=Sunday..6=Saturday)
- `defaultLocation` — free-text input with placeholder

Both fields flow through `CalendarGeneralSettings` ↔ `UserCalendarGeneral`
mapping in `calendar-utils.tsx` and validate in the zod schema.

**Change Status**: ✅ COMPLETE
**Last Updated**: 2026-08-06
