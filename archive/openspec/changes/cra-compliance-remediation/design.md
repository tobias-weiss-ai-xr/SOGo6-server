# Design — CRA Compliance Remediation

## Architecture

The remediation is organized as **5 workstreams** that map directly to CRA articles.
Each workstream has a gate: a CI check or artifact that proves the requirement is met.

```
┌─────────────────────────────────────────────────────────────────┐
│                    CRA Compliance Remediation                    │
├─────────────┬──────────────┬──────────────┬──────────┬──────────┤
│  WS-1       │  WS-2        │  WS-3        │  WS-4    │  WS-5    │
│  Security   │  Security    │  Supply      │  Audit   │  CRA     │
│  Headers &  │  Testing &   │  Chain &     │  Log &   │  Docs &  │
│  Hardening  │  Threat Model│  SBOM        │  Incident│  Process │
│             │              │              │  Response│          │
│  Art.15     │  Art.10,15   │  Art.13,29   │  Art.11  │  Art.24, │
│             │              │              │          │  30,17   │
├─────────────┼──────────────┼──────────────┼──────────┼──────────┤
│ G1: Headers │ G2: Sec e2e  │ G3: Trivy    │ G8: Audit│ G12:Tech │
│ G6: Default │ G5: STRIDE   │ G4: SBOM     │   format │   file   │
│   pwd       │ G11: Pentest │   deploy     │ G13: IR  │ G14:SCA  │
│ G9: CSP     │              │              │ G7:ENISA │ G7:ENISA │
│ G10:MFA     │              │              │          │          │
├─────────────┼──────────────┼──────────────┼──────────┼──────────┤
│ Traefik     │ 4 new e2e    │ CI pipeline  │ Audit    │ 3 new   │
│ middleware  │ spec files + │ fix + deploy │ pipeline │ docs    │
│ + server    │ threat-model │ gate         │ + format │ + CI    │
│ hardening   │ doc          │              │          │          │
├─────────────┼──────────────┼──────────────┼──────────┼──────────┤
│ ~4h        │ ~12h         │ ~3h          │ ~6h      │ ~4h      │
└─────────────┴──────────────┴──────────────┴──────────┴──────────┘
```

---

## Workstream 1: Security Headers & Hardening (Art. 15)

### G1 — Traefik Security Headers Middleware

**Problem**: The Traefik `websecure@file` middleware is referenced in `docker-compose.traefik.yaml`
but no file defines it. Traefik falls back to its built-in (minimal) defaults.

**Solution**: Create a Traefik dynamic configuration file `traefik/dynamic/security-headers.yaml`
with a `security-headers@file` middleware, then reference it from the routers.

```yaml
# traefik/dynamic/security-headers.yaml
http:
  middlewares:
    security-headers:
      headers:
        stsSeconds: 63072000          # 2 years (HSTS preload eligible)
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true
        frameDeny: true               # X-Frame-Options: DENY
        contentTypeNosniff: true      # X-Content-Type-Options: nosniff
        browserXssFilter: true        # X-XSS-Protection (legacy, defense-in-depth)
        referrerPolicy: "strict-origin-when-cross-origin"
        contentSecurityPolicy: "default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://sogo6.contextual-intelligence.org wss://sogo6.contextual-intelligence.org; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        permissionsPolicy: "camera=(), microphone=(), geolocation=()"
        customResponseHeaders:
          X-Permitted-Cross-Domain-Policies: "none"
          Cross-Origin-Opener-Policy: "same-origin"
          Cross-Origin-Resource-Policy: "same-origin"
```

**Router attachment** (modify `docker-compose.traefik.yaml`):
```yaml
traefik.http.routers.sogo6-ui.middlewares: "security-headers@file"
traefik.http.routers.sogo6-api.middlewares: "security-headers@file"
```

**Gate**: CI step that `curl -skI` checks for 6 mandatory headers (HSTS, CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy). Fail on any missing.

### G6 — Eliminate Default Admin Password

**Problem**: `sogo6/config/process.conf:81` ships `SOGO_P_ADMIN_PWD=admin`.

**Solution**:
1. Change default to empty string with startup guard: if `SOGO_P_ADMIN_PWD` is empty or `admin`,
   the server refuses to start with a clear error message.
2. Update `.env.example` to use `SOGO_P_ADMIN_PWD=` (empty, must be set by operator).
3. Add CI check: `grep -q 'SOGO_P_ADMIN_PWD=admin' sogo6/config/process.conf` → fail.

### G9 — Next.js CSP Nonce Integration

**Problem**: The CSP from Traefik uses a static policy, but Next.js injects inline scripts.

**Solution**:
1. Configure Next.js `headers()` in `next.config.ts` to set a per-request CSP with nonce.
2. Alternatively (simpler): use Traefik CSP with `'unsafe-inline'` for script-src as interim measure,
   with a TODO to migrate to nonce-based CSP in a future change.
3. For this remediation: allow `'unsafe-inline'` in `script-src` and `'unsafe-inline'` in `style-src`
   since Next.js requires both. This still protects against external script injection.

### G10 — Enforce MFA for Admin

**Problem**: MFA available but not enforced even for admin accounts.

**Solution**:
1. Add `SOGO_D_ADMIN_MFA_FORCE=true` to `process.conf` defaults.
2. The server already supports `SOGO_D_LOGIN_MFA_FORCE` — set it to `true` in the sample config.
3. Document that operators can override to `false` for development.

---

## Workstream 2: Security Testing & Threat Model (Art. 10, 15)

### G5 — STRIDE Threat Model Document

**Solution**: Create `docs/THREAT-MODEL.md` using STRIDE methodology:

| STRIDE Category | Applicable Threats | Existing Mitigations | Gaps | Remediation |
|-----------------|-------------------|---------------------|------|-------------|
| **S**poofing | LDAP credential theft, JWT forgery, session hijacking | Rate limiting, JWT signing, HttpOnly cookies | No token rotation, no IP-binding | Add token rotation (P2) |
| **T**ampering | Sieve filter injection, calendar event manipulation, mail send as other user | Auth guard on all endpoints | No request signing, no integrity checks on critical mutations | Add idempotency keys for mail send (P2) |
| **R**epudiation | User deletes evidence mail, admin denies action | Audit log module exists | No immutable audit, no log integrity | Hash-chain audit (P1 in this workstream) |
| **I**nformation Disclosure | IDOR on calendar/addressbook, admin sees user mail, LDAP data leak | Role-scoped tokens, auth guard | No IDOR testing, no field-level authorization | Add IDOR e2e tests (this workstream) |
| **D**enial of Service | Login brute force, mail bomb, API flood | Login rate limiter (20/60s) | No global API rate limit, no request size limit | Add global rate limiter (P2) |
| **E**levation of Privilege | User accesses admin API, impersonates other user | Separate admin/user auth | No test that user JWT fails on admin endpoints | Add privilege escalation tests (this workstream) |

### G2 — Security-Focused E2E Test Suite

Four new spec files, each targeting a distinct attack surface:

#### `epic-security-injection.spec.ts` (Art. 10(1)(c))

| Story ID | Test | Method | Assertion |
|----------|------|--------|-----------|
| INJ-01 | SQL injection in calendar event title | POST `/events` with `' OR 1=1--` | 400/422, no 5xx, data not persisted |
| INJ-02 | XSS in contact display name | POST `/contacts` with `<script>alert(1)</script>` | 200 but script content sanitized/escaped in GET response |
| INJ-03 | Path traversal in addressbook name | POST `/address-books` with `../../etc/passwd` | 400/422 |
| INJ-04 | LDAP injection in login | POST `/auth/login` with `*)(uid=*))(|` | 401, no 5xx |
| INJ-05 | JSON bomb (deeply nested) on generic POST | POST `/events` with 1000-deep JSON | 413 or 400, no 5xx |
| INJ-06 | Oversized body (50MB) on mail send | POST `/mailboxes/0/mails` with huge payload | 413 or 400, no timeout/5xx |
| INJ-07 | Null bytes in path params | GET `/mailboxes/0/folders/INBOX%00/../../admin` | 400/404, not 200 with admin data |
| INJ-08 | CRLF injection in mail subject | POST with `subject=foo\r\nX-Injected: bar` | 200/201 but header not injected (check response) |
| INJ-09 | IMAP command injection via folder name | POST `/mailboxes/0/folders` with name containing `\r\nEXAMINE INBOX` | 400/422 |
| INJ-10 | Unicode normalization attack | Login with homoglyph `admin` (Cyrillic а) | 401 (not authenticated as real admin) |

#### `epic-security-authz-bypass.spec.ts` (Art. 10(1)(c))

| Story ID | Test | Method | Assertion |
|----------|------|--------|-----------|
| AUTHZ-01 | User JWT on admin endpoint | GET `/admin/v1/users` with user token | 401/403 |
| AUTHZ-02 | Admin JWT on user endpoint | GET `/user/v1/profile` with admin token | 401/403 or 200 (if admin can impersonate, document it) |
| AUTHZ-03 | No token on protected endpoint | GET `/user/v1/mailboxes` with no Authorization | 401/403/404 |
| AUTHZ-04 | Expired token | JWT with `exp` in the past | 401 |
| AUTHZ-05 | Tampered token (wrong signature) | JWT with modified payload | 401 |
| AUTHZ-06 | Cross-user calendar read | User A tries GET on User B's private calendar ID | 403/404 |
| AUTHZ-07 | Cross-user addressbook write | User A POSTs contact to User B's addressbook | 403/404 |
| AUTHZ-08 | Cross-user mail read | User A reads User B's mailbox via API | 403/404 |
| AUTHZ-09 | Deleted-user token still works | Login, delete user (admin), reuse old token | 401 |
| AUTHZ-10 | App password on admin endpoint | Use app-password JWT on `/admin/v1/` | 401/403 |

#### `epic-security-rate-limit-abuse.spec.ts` (Art. 10(1)(c))

| Story ID | Test | Method | Assertion |
|----------|------|--------|-----------|
| RL-01 | Brute-force login (21 attempts in 60s) | 21x POST `/auth/login` with wrong password | Last 1+ return 429 |
| RL-02 | Rate limit resets after window | Wait 61s, retry | 200 (login succeeds) |
| RL-03 | Distributed login (different IPs) | 20 from IP-A, 20 from IP-B | All succeed (per-IP limit) |
| RL-04 | Non-login endpoint flood | 100 rapid GETs to `/user/v1/profile` | No 429 (login-only rate limit is OK, document) OR 429 (global limit) |
| RL-05 | Admin login rate limit | 21x POST `/admin/v1/auth/login` wrong | 429 after 20 |

#### `epic-security-data-isolation.spec.ts` (Art. 10(1)(c))

| Story ID | Test | Method | Assertion |
|----------|------|--------|-----------|
| ISO-01 | User A calendar doesn't leak to User B | Create event as A, list B's calendars, search for A's event title | Not found |
| ISO-02 | User A contacts not in User B's addressbook | Create contact as A, search B's addressbook | Not found |
| ISO-03 | User A mail not in User B's mailbox | Send mail A→B, check A's sent vs B's inbox separately | Only in correct mailbox |
| ISO-04 | User A tasks not visible to User B | Create task as A, list B's tasks | Not found |
| ISO-05 | User A preferences don't affect User B | Set A's language to `de`, check B's language | B's language unchanged |
| ISO-06 | Admin can list but not read user mail content | Admin lists users, then tries to read user's mail body | 403 or empty |

### G11 — OWASP ZAP Baseline Scan

**Solution**: Add OWASP ZAP baseline scan to CI:

```yaml
# In .github/workflows/test.yml
owasp-zap:
  name: OWASP ZAP Baseline
  runs-on: ubuntu-latest
  needs: [security]
  steps:
    - uses: actions/checkout@v4
    - name: ZAP Baseline Scan
      uses: zaproxy/action-full-scan@v0.10.0
      with:
        target: 'http://localhost:50000/'
        rules_file_name: 'zap-rules.tsv'
        cmd_options: '-a -j -t 5'
      continue-on-error: true  # initially, until baseline is clean
```

Create `tests/zap-rules.tsv` to suppress false positives (e.g., CSP warnings
until G9 is fully implemented with nonces).

---

## Workstream 3: Supply Chain & SBOM (Art. 13, 29)

### G3 — Fix Trivy CI Gate

**Problem**: All 3 Trivy steps in `test.yml` use `continue-on-error: true`, which means
HIGH/CRITICAL vulnerabilities never fail CI.

**Solution**:
1. Remove `continue-on-error: true` from Trivy steps.
2. Add `--ignore-unfixed` flag to avoid failing on CVEs without patches.
3. Add `.trivyignore` file for known-accepted risks (with documented justification).
4. Add Trivy image scan on the actual built images (not just Dockerfile config scan).

### G4 — SBOM Verification on Deploy

**Solution**:
1. Create `scripts/verify-sbom.sh` that:
   - Generates SBOM from the about-to-deploy image
   - Compares against baseline SBOM in `sbom/` directory
   - Runs `trivy sbom` to check for known CVEs
   - Exits non-zero if new CRITICAL/HIGH CVEs introduced
2. Add to deploy pipeline (Ansible or manual deploy)
3. Store SBOMs per release in `sbom/releases/<tag>/`

---

## Workstream 4: Audit Logging & Incident Response (Art. 11, 17)

### G8 — Security Audit Log Standard

**Solution**: Enhance `ApiAuditLog.py` with:

1. **Structured event format** (SIEM-consumable):
   ```python
   {
     "timestamp": "2026-08-26T14:30:00Z",
     "event_type": "auth.login.success|auth.login.failure|auth.mfa.challenge|admin.user.create|...",
     "severity": "info|warning|critical",
     "actor": {"uid": "testuser@...", "ip": "1.2.3.4", "user_agent": "..."},
     "resource": {"type": "user|calendar|mailbox|...", "id": "..."},
     "action": "create|read|update|delete|login|logout",
     "outcome": "success|failure|denied",
     "metadata": {}
   }
   ```

2. **Mandatory audit events**:
   - All authentication events (success, failure, MFA, token refresh)
   - All admin actions (user create/delete, config change, role change)
   - All authorization failures (403 responses)
   - All rate-limit triggers (429 responses)
   - All password changes

3. **Log integrity**: SHA-256 hash chain (each entry includes hash of previous).
   SECURITY.md already claims this exists — verify it works or implement it.

4. **Retention**: Configurable via `SOGO_D_AUDIT_RETENTION_DAYS` (default: 365).

### G13 — Incident Response Playbook

**Solution**: Create `docs/INCIDENT-RESPONSE.md`:

1. **Severity classification**: P1 (active exploitation) → P4 (informational)
2. **Timeline**:
   - P1: Acknowledge within 1h, contain within 4h, notify CSIRT within 24h
   - P2: Acknowledge within 4h, fix within 7 days
   - P3: Fix in next release
   - P4: Track, fix opportunistically
3. **Roles**: Incident Commander, Technical Lead, Communications
4. **Art. 14(3) template**: Pre-drafted ENISA/CSIRT notification with fields
5. **Post-incident**: Blameless retrospective template

### G7 — Automated ENISA/CSIRT Notification Helper

**Solution**: Create `scripts/notify-csirt.sh` — a template script that:
- Accepts vulnerability details as arguments
- Generates a structured notification in the format required by Art. 14(3)
- Outputs JSON+PDF ready for submission
- Does NOT auto-send (operator responsibility)

---

## Workstream 5: CRA Documentation & Process (Art. 24, 30, 17)

### G12 — Technical Documentation (Art. 24 / Annex V)

**Solution**: Create `docs/TECHNICAL_FILE.md` following Annex V structure:

1. Product description and intended use
2. Architecture diagram (system context, data flow)
3. Security architecture (auth, encryption, audit)
4. List of standards applied (OWASP, RFC 9116, etc.)
5. Test coverage report (link to CI badges)
6. SBOM reference
7. Known limitations and accepted risks
8. Installation and configuration guide
9. Support and update commitment

### G14 — Self-Assessment Evidence (Art. 30)

**Solution**: Create `docs/CONFORMITY-ASSESSMENT.md`:

1. Checklist of all CRA requirements with evidence links
2. Test results summary (CI badges, e2e pass rate)
3. SBOM + vulnerability scan results
4. Security test results (ZAP, injection, authz)
5. Threat model reference
6. Gap register with remediation status
7. Assessment date, assessor, next review date

### G7 (continued) — Update SECURITY.md

Add:
- Link to incident response playbook
- Link to technical file
- Link to conformity assessment
- SBOM generation evidence
- ENISA/CSIRT notification procedure

---

## Priority & Dependency Order

```
Phase 1 (Critical — blocks CRA compliance)
  ┌─ WS-1: Security Headers (G1, G6, G9, G10)     ~4h
  ├─ WS-3: Trivy CI fix (G3)                       ~1h
  └─ WS-2: Authz bypass tests (G2 subset)           ~3h

Phase 2 (High — completes technical measures)
  ┌─ WS-2: Injection + isolation + rate-limit tests  ~6h
  ├─ WS-2: Threat model (G5)                        ~2h
  └─ WS-3: SBOM deploy verification (G4)             ~2h

Phase 3 (Medium — process & documentation)
  ┌─ WS-4: Audit log standard (G8)                   ~4h
  ├─ WS-4: Incident response (G13, G7)               ~3h
  ├─ WS-5: Technical file (G12)                      ~2h
  └─ WS-5: Conformity assessment (G14)               ~2h

Phase 4 (Ongoing)
  └─ WS-2: OWASP ZAP CI integration (G11)          ~2h
```

## Verification Gates

Each phase is complete when:

| Gate | Check | Automated? |
|------|-------|------------|
| G1-headers | `curl` checks 6 headers present | ✅ CI |
| G6-no-default-pwd | `grep` fails on `admin` default | ✅ CI |
| G3-trivy-gates | Trivy HIGH/CRITICAL fails CI | ✅ CI |
| G2-authz-tests | 10 authz stories pass | ✅ CI |
| G2-injection-tests | 10 injection stories pass | ✅ CI |
| G5-threat-model | Document reviewed, no empty cells | Manual |
| G4-sbom-deploy | Deploy script runs SBOM check | ✅ Deploy |
| G8-audit-format | Audit events match schema | ✅ CI (unit test) |
| G12-tech-file | Document exists with all Annex V sections | Manual |
| G14-assessment | Checklist 100% green or gaps documented | Manual |
