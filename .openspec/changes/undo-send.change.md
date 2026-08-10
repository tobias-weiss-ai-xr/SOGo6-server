# Undo Send Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | undo-send |
| **Title** | Implement Undo Send Feature |
| **Status** | Complete |
| **Priority** | High |
| **Type** | Feature Implementation |
| **Created** | 2026-08-06 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 1 Core Experience |
| **Spec** | [mail.spec.md](../specs/mail.spec.md) (Special Features: Undo send) |

---

## Overview

Completion of the **Undo Send** feature (ROADMAP Tier 1 #12 — "Low effort, high
gratitude. Safety net for composed emails"). The backend already held pending
emails in Redis with a grace period but **never delivered them** after the
window elapsed — the deferred delivery job was missing. This change closes that
gap and adds the frontend undo UX.

## Related Artifacts

- **Specification**: [mail.spec.md](../specs/mail.spec.md)
- **Roadmap**: [ROADMAP.md](../../ROADMAP.md) Tier 1 #12
- **Parent Change**: [tier1-implementation.change.md](./tier1-implementation.change.md)

## Goals

See specification: [mail.spec.md](../specs/mail.spec.md)

## Tasks

- [x] Backend: `app/agent/jobs/UndoSendJob.py` — delivers pending emails after the grace period
  (rebuilds user from session, sends via ModuleMailOutgoing, saves to Sent, deletes Redis entry)
- [x] Backend: `InterfaceApiMailSend.send_mail` undo path — enqueues `UndoSendRequest` with
  `eta = now + undo_seconds`; stores user session + outgoing login in the pending payload;
  TTL extended past the grace period so a delayed worker still finds the entry;
  falls back to immediate send if job enqueue fails
- [x] Backend: tests — `tests/test_agent/test_JobUndoSend.py` (6) + updated undo-send
  interface tests in `test_InterfaceApiMailSend.py`
- [x] Frontend: `cancelPendingSend` RTK mutation + `useCancelPendingSendMutation` hook
  (`POST mailboxes/:accountId/mail/pending/:pendingKey/cancel`)
- [x] Frontend: `SendMailResult` / `CancelPendingSendArg` types; `sendMail` returns the result
- [x] Frontend: `useComposeSend` — on `status === 'pending'` keeps the draft open and shows an
  "Email sent — Undo" toast with a countdown; Undo calls cancelPendingSend
- [x] i18n: `mail_send.undo.*`, `mail_send.undo_cancelled.*`, `mail_send.undo_cancel_error.*`
  in `src/messages/en/notifications.json`
- [x] Tests: 3 new undo-send hook tests + floating-compose mock fix; structural mail-api tests

## Success Criteria

- [x] Sending an email with `SOGO_U_UNDO_SEND_SECONDS > 0` returns `status: pending` + `pending_key`
- [x] The email is actually delivered after the grace period (UndoSendJob)
- [x] Cancelling within the window prevents delivery (`POST .../pending/<key>/cancel`)
- [x] Cancelling after the window returns the "expired" error (backend TTL + created_at check)
- [x] The frontend shows an Undo toast and keeps the draft open; Undo cancels the send
- [x] Immediate (non-pending) sends still close the draft as before
- [x] No regressions: backend 873 passed / frontend mails suite 1423 passed

## Implementation Details

**Delivery job (`UndoSendJob`)**: reads `undo_send:{uid}:{pending_key}` from
Redis. Missing entry → no-op (cancelled / expired). Present entry → rebuilds the
`User` from the stored session + outgoing login, loads the profile, sends via
`ModuleMailOutgoing.send_mail`, saves to the Sent folder, cleans the tmp_draft,
then deletes the Redis entry so at-least-once delivery never double-sends. A
delivery failure re-raises so the agent retry picks it up (entry kept).

**Frontend**: `useComposeSend.performSend` inspects the send response. When the
server returns `status: 'pending'`, the compose window stays open and a sonner
toast ("Email sent" + Undo action) is shown for the remaining undo window.
Clicking Undo dispatches `cancelPendingSend({ accountId, pendingKey })`. All
other outcomes (sent / scheduled / error) behave exactly as before.

**Change Status**: ✅ COMPLETE
**Last Updated**: 2026-08-06
