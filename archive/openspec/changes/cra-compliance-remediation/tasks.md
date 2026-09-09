# Tasks — CRA Compliance Remediation

## Phase 1: Critical (blocks compliance)

### WS-1: Security Headers & Hardening

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-01 | Create `traefik/dynamic/security-headers.yaml` with HSTS/CSP/X-Frame-Options/Referrer-Policy/Permissions-Policy | `traefik/dynamic/security-headers.yaml` (new) | 30m | ☐ |
| T-02 | Mount the Traefik dynamic config volume in `docker-compose.traefik.yaml` and attach `security-headers@file` to `sogo6-ui` and `sogo6-api` routers | `docker-compose.traefik.yaml` | 30m | ☐ |
| T-03 | Write `tests/e2e/specs/security-headers.spec.ts` — verify 6 mandatory headers via `curl -skI` or Playwright `request.fetch` | `tests/e2e/specs/security-headers.spec.ts` (new) | 30m | ☐ |
| T-04 | Change `process.conf:81` default admin password from `admin` to empty string, add server startup guard that refuses to start if `SOGO_P_ADMIN_PWD` is unset or `admin` | `sogo6/config/process.conf`, `sogo6-server/app/config/init_config.py` | 45m | ☐ |
| T-05 | Update `.env.example` to document `SOGO_P_ADMIN_PWD` is mandatory, remove default value | `.env.example` | 10m | ☐ |
| T-06 | Enable admin MFA enforcement: set `SOGO_D_LOGIN_MFA_FORCE=true` in sample `process.conf` | `sogo6/config/process.conf` | 10m | ☐ |

### WS-3: Trivy CI Fix

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-07 | Remove `continue-on-error: true` from all 3 Trivy steps in `.github/workflows/test.yml` | `.github/workflows/test.yml` | 10m | ☐ |
| T-08 | Add `--ignore-unfixed` flag to Trivy steps (avoid failing on unpatchable CVEs) | `.github/workflows/test.yml` | 10m | ☐ |
| T-09 | Create `.trivyignore` with documented accepted risks | `.trivyignore` (new) | 20m | ☐ |

### WS-2: Critical Auth Tests

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-10 | Write `epic-security-authz-bypass.spec.ts` — 10 stories for privilege escalation, cross-user access, token tampering, expired tokens | `tests/e2e/specs/epic-security-authz-bypass.spec.ts` (new) | 90m | ☐ |
| T-11 | Write `epic-security-injection.spec.ts` — 10 stories for SQL injection, XSS, path traversal, LDAP injection, JSON bomb, CRLF, Unicode homoglyphs | `tests/e2e/specs/epic-security-injection.spec.ts` (new) | 90m | ☐ |
| T-12 | Run Phase 1 tests over live server, verify all pass | — | 15m | ☐ |
| T-13 | Commit Phase 1 | — | 5m | ☐ |

---

## Phase 2: High (completes technical measures)

### WS-2: Security Testing (cont.)

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-14 | Write `epic-security-rate-limit-abuse.spec.ts` — 5 stories for brute-force, window reset, distributed login, non-login flood, admin rate limit | `tests/e2e/specs/epic-security-rate-limit-abuse.spec.ts` (new) | 60m | ☐ |
| T-15 | Write `epic-security-data-isolation.spec.ts` — 6 stories for cross-user data isolation (calendar, contacts, mail, tasks, preferences, admin boundary) | `tests/e2e/specs/epic-security-data-isolation.spec.ts` (new) | 60m | ☐ |
| T-16 | Run Phase 2 tests, verify all pass | — | 10m | ☐ |

### WS-2: Threat Model

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-17 | Write `docs/THREAT-MODEL.md` with STRIDE analysis for all 8 attack surfaces (see design.md) | `docs/THREAT-MODEL.md` (new) | 90m | ☐ |
| T-18 | Review threat model, validate mitigations against existing code | — | 30m | ☐ |

### WS-3: SBOM Deploy Verification

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-19 | Write `scripts/verify-sbom.sh` — generates SBOM from image, compares to baseline, checks for new CRITICAL/HIGH CVEs | `scripts/verify-sbom.sh` (new) | 60m | ☐ |
| T-20 | Integrate `verify-sbom.sh` into deploy script/Ansible playbook | `scripts/deploy-standalone.sh` or Ansible | 30m | ☐ |
| T-21 | Store per-release SBOMs in `sbom/releases/<tag>/` | CI workflow update | 30m | ☐ |

---

## Phase 3: Medium (process & documentation)

### WS-4: Audit Logging

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-22 | Define security audit event schema (JSON, see design.md) and create `app/utils/audit_schema.py` | `sogo6-server/app/utils/audit_schema.py` (new) | 45m | ☐ |
| T-23 | Add audit event emission to: auth success/failure, admin actions, 403 responses, 429 responses, password changes | `sogo6-server/app/module/auth/ModuleAuth.py`, `sogo6-server/app/api/v1/admin/*.py` | 90m | ☐ |
| T-24 | Verify or implement SHA-256 hash chain for audit log integrity | `sogo6-server/app/api/v1/admin/ApiAuditLog.py` | 45m | ☐ |
| T-25 | Add `SOGO_D_AUDIT_RETENTION_DAYS` config (default 365), implement log rotation | `sogo6-server/app/config/settings/ProcessSetting.py` | 30m | ☐ |
| T-26 | Write unit tests for audit event schema validation | `sogo6-server/tests/test_module/test_audit/test_audit_schema.py` (new) | 30m | ☐ |

### WS-4: Incident Response

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-27 | Write `docs/INCIDENT-RESPONSE.md` with severity levels, timelines, roles, Art.14(3) template | `docs/INCIDENT-RESPONSE.md` (new) | 60m | ☐ |
| T-28 | Write `scripts/notify-csirt.sh` — generates Art.14(3) structured notification from CLI args | `scripts/notify-csirt.sh` (new) | 45m | ☐ |

### WS-5: CRA Documentation

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-29 | Write `docs/TECHNICAL_FILE.md` following Annex V structure (see design.md) | `docs/TECHNICAL_FILE.md` (new) | 90m | ☐ |
| T-30 | Write `docs/CONFORMITY-ASSESSMENT.md` with CRA requirement checklist, evidence links, gap register | `docs/CONFORMITY-ASSESSMENT.md` (new) | 60m | ☐ |
| T-31 | Update `SECURITY.md` to link new docs (IR playbook, technical file, conformity assessment) | `SECURITY.md` | 15m | ☐ |
| T-32 | Update `CRA-READINESS.md` with accurate status (remove inflated claims, reference evidence) | `CRA-READINESS.md` | 30m | ☐ |

---

## Phase 4: Ongoing

| ID | Task | File(s) | Est. | Done? |
|----|------|---------|------|-------|
| T-33 | Add OWASP ZAP baseline scan to `.github/workflows/test.yml` with `zap-rules.tsv` | `.github/workflows/test.yml`, `tests/zap-rules.tsv` (new) | 60m | ☐ |
| T-34 | Tune ZAP rules, remove false-positive suppressions, make scan non-continue-on-error | `.github/workflows/test.yml` | 30m | ☐ |
| T-35 | Add CSP nonce integration in Next.js to replace `unsafe-inline` | `sogo6-ui/next.config.ts`, middleware | 120m | ☐ |
| T-36 | Add global API rate limiter (beyond login-only) | `sogo6-server/app/utils/api/` | 120m | ☐ |
| T-37 | Token rotation (refresh token → new access token, invalidate old) | `sogo6-server/app/module/auth/` | 180m | ☐ |

---

## Summary

| Phase | Tasks | Est. Hours | Key Deliverable |
|-------|-------|------------|-----------------|
| 1 — Critical | T-01 to T-13 | **~7h** | Headers live, Trivy gates real, 20 security tests green |
| 2 — High | T-14 to T-21 | **~7h** | 11 more security tests, STRIDE model, SBOM deploy gate |
| 3 — Medium | T-22 to T-32 | **~10h** | Structured audit, IR playbook, CRA technical file, self-assessment |
| 4 — Ongoing | T-33 to T-37 | **~8.5h** | ZAP in CI, nonce CSP, global rate limit, token rotation |
| **Total** | **37 tasks** | **~32.5h** | **Full CRA technical groundwork** |

## CRA Gap Closure Tracking

| Gap | Task(s) | WS | Phase | Target Status |
|-----|---------|-----|-------|---------------|
| G1 Security headers | T-01, T-02, T-03 | WS-1 | P1 | ✅ Closed |
| G2 Security e2e tests | T-10, T-11, T-14, T-15 | WS-2 | P1+P2 | ✅ Closed |
| G3 Trivy CI gate | T-07, T-08, T-09 | WS-3 | P1 | ✅ Closed |
| G4 SBOM deploy verification | T-19, T-20, T-21 | WS-3 | P2 | ✅ Closed |
| G5 Threat model | T-17, T-18 | WS-2 | P2 | ✅ Closed |
| G6 Default admin password | T-04, T-05 | WS-1 | P1 | ✅ Closed |
| G7 ENISA/CSIRT automation | T-28 | WS-4 | P3 | 🚧 Partial (helper script, operator sends) |
| G8 Audit log standard | T-22, T-23, T-24, T-25, T-26 | WS-4 | P3 | ✅ Closed |
| G9 CSP for UI | T-01 (interim), T-35 (full) | WS-1, P4 | P1+P4 | 🚧 Interim in P1, full in P4 |
| G10 MFA enforced | T-06 | WS-1 | P1 | ✅ Closed |
| G11 Pentest evidence | T-33, T-34 | WS-2 | P4 | ✅ Closed |
| G12 Technical documentation | T-29 | WS-5 | P3 | ✅ Closed |
| G13 Incident response | T-27 | WS-4 | P3 | ✅ Closed |
| G14 Self-assessment | T-30, T-31, T-32 | WS-5 | P3 | ✅ Closed |
