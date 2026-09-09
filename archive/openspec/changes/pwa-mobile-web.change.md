# PWA / Mobile Web Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | pwa-mobile-web |
| **Title** | Implement PWA / Mobile Web Feature |
| **Status** | Complete |
| **Priority** | High |
| **Type** | Feature Implementation |
| **Created** | 2026-08-06 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 1 Core Experience |
| **Spec** | [mail.spec.md](../specs/mail.spec.md) / [calendar.spec.md](../specs/calendar.spec.md) |

---

## Overview

**PWA / Mobile Web** (ROADMAP Tier 1 #17) — mobile reach without a native app:
installable web app (manifest + icons), offline support (service worker +
offline page), and app-shell precaching. This is the **final Tier 1 feature** —
completing the Core Experience tier.

The app already registered a service worker and shipped a manifest, but the
icons referenced by both were **missing**, the offline route didn't exist, and
the service worker had duplicate branches and wrong icon paths. This change
completes the PWA story end-to-end.

## Related Artifacts

- **Roadmap**: [ROADMAP.md](../../ROADMAP.md) Tier 1 #17
- **Parent Change**: [tier1-implementation.change.md](./tier1-implementation.change.md)

## Goals

Mobile reach without native app: offline cache, share target, installable
web app.

## Tasks

- [x] Generate missing PWA icons — `icons/icon-192.png`, `icons/icon-512.png`
  (maskable, from the 512×512 SOGo SVG) and `icons/badge-72x72.png`
- [x] Fix `public/manifest.json` — `id`, `start_url: /en`, `scope: /`,
  `display_override`, app **shortcuts** (Mail / Calendar / Contacts)
- [x] Rewrite `public/sw.js` — single navigation branch (network-first →
  offline fallback), stale-while-revalidate for static assets, never caches
  API/fakeApi/env, correct icon paths, notification + sync handlers kept
- [x] Add `/offline` fallback page (`src/app/offline/page.tsx`) with retry link
- [x] Point Apple touch icon at the generated 192px PNG in `app/layout.tsx`
- [x] Tests — `src/app/__tests__/pwa.test.ts` (16 structural assertions:
  manifest fields, sw handlers + icon existence + API-exclusion, offline page,
  layout registration)
- [x] Docs

## Success Criteria

- [x] Installable: valid manifest with existing 192/512 maskable icons
- [x] Offline: service worker precaches the app shell and serves `/offline`
  when a navigation fails
- [x] API calls are never cached (fresh data always)
- [x] App shortcuts launch Mail / Calendar / Contacts directly
- [x] iOS: apple-touch-icon + appleWebApp metadata present
- [x] No regressions: frontend app suites 292 passed, tsc unchanged (459)

## Implementation Details

**Icons**: generated from `public/icons/icon.svg` (512×512 blue rounded square
with white envelope/calendar/contact glyphs) at 192, 512 and 72 px via
ImageMagick.

**Manifest**: added `id`, `scope: "/"`, `start_url: "/en"` (the locale-routed
home), `display_override: ["window-controls-overlay", "standalone"]`, and three
`shortcuts` (Mail → `/en/u/0/INBOX`, Calendar → `/en/calendars`,
Contacts → `/en/address_books`).

**Service worker**: rewritten with a single fetch handler — navigations use
network-first with cache fallback to `OFFLINE_URL`; static assets use
stale-while-revalidate; `/api/`, `/fakeApi/` and `/env` are never cached. Push
notification, notificationclick, pushsubscriptionchange and background-sync
handlers preserved, with icon paths fixed to the generated assets.

**Offline page**: standalone (own `<html>`/`<body>` like `not-found.tsx`) with
a wifi-off icon, message and a Retry link.

**Change Status**: ✅ COMPLETE
**Last Updated**: 2026-08-06
