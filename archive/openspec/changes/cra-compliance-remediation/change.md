# CRA Compliance Remediation — Full Gap Closure

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | cra-compliance-remediation |
| **Title** | CRA Compliance Remediation — Full Gap Closure |
| **Status** | Planned |
| **Priority** | Critical |
| **Type** | Compliance & Security Hardening |
| **Created** | 2026-08-26 |
| **Author** | pi-coding-agent |
| **CRA Articles** | 10, 11, 13, 14, 15, 24, 29 |
| **Target Compliance** | EU 2024/2847 (Cyber Resilience Act), effective 2024-12-11, enforcement from 2027-01-11 |
| **Compliance Deadline** | 2026-12-11 (18-month transition period ends) |

---

## Current State Assessment (2026-08-26)

### What Exists

| Area | Artifact | Status | Quality |
|------|----------|--------|--------|
| Vulnerability policy | `SECURITY.md` | ✅ Good | RFC 9116 `security.txt` live; coordinated disclosure timeline; 48h ACK; 30d fix target |
| SBOM generation | `scripts/generate-sbom.sh` | ⚠️ Partial | Manual script, not CI-gated; output not verified on deploy |
| Dependency scanning | `.github/workflows/test.yml` Trivy | ⚠️ Partial | `continue-on-error: true`; HIGH/CRITICAL gate does NOT fail CI |
| Auth breadth | JWT, WebAuthn, TOTP, SAML2, OIDC, app passwords | ✅ Good | 6 auth mechanisms |
| Rate limiting | `login_rate_limiter.py`, `ratelimit.py` | ✅ Good | IP-based (20/60s) + per-UID brute-force |
| Audit log module | `ApiAuditLog.py` | ⚠️ Weak | Module exists but no centralized security-event format, no retention |
| Six-Sigma CI | `six-sigma-compliance.yml` | ✅ Good | OpenSpec spec compliance check, weekly cron |
| Test CI | `test.yml` | ✅ Good | Backend unit (184 pytest), e2e Playwright |
| TLS | Traefik HTTPS | ✅ Good | Certificate via Let's Encrypt |

### What's Missing (Critical Gaps)

| # | Gap | CRA Article | Severity | Impact | Current Evidence |
|---|-----|-------------|----------|--------|-------------------|
| G1 | No security headers on live site | 15(1) | **Critical** | No HSTS, CSP, X-Frame-Options, Referrer-Policy. Traefik `websecure@file` referenced but file missing | `curl -skI` returns none of the standard headers |
| G2 | Zero security-focused e2e tests | 10(1)(c) | **Critical** | 0 of 245+ e2e tests check for injection, auth bypass, privilege escalation, or input validation | grep of all specs returns 0 files |
| G3 | Trivy CI gate doesn't fail | 13(5) | **High** | `continue-on-error: true` means HIGH/CRITICAL vulns don't block PRs | test.yml line 29 |
| G4 | SBOM not verified on deployment | 29(4) | **High** | Generated but never checked against known-CVE database at deploy time | No deploy-time verification |
| G5 | No threat model or STRIDE analysis | 15 | **High** | No formal threat model document; security decisions are ad-hoc | No *threat-model* doc in repo |
| G6 | Default admin password in shipped config | 15(1) | **High** | `process.conf:81` ships `SOGO_P_ADMIN_PWD=admin` | Any deployment using default config is compromised |
| G7 | No automated ENISA/CSIRT notification | 14(3) | **High** | Process documented but no automation | SECURITY.md documents manual process only |
| G8 | No security audit log standard | 11 | **Medium** | `ApiAuditLog.py` exists but no CSIRT-compatible event format, no integrity, no retention policy | No SIEM integration evidence |
| G9 | No CSP policy for UI | 15(1) | **Medium** | Next.js app has no Content-Security-Policy; no nonce-based inline script protection | `next.config.*` has zero CSP config |
| G10 | MFA not enforced by default | 15(1) | **Medium** | `SOGO_D_LOGIN_MFA_FORCE` exists but defaults to false | Server log: "MFA is not enforced" warning |
| G11 | No penetration test evidence | 10(1)(c) | **Medium** | No pentest, no OWASP ZAP, no Burp Suite evidence | Zero pentest reports in repo |
| G12 | No formal Art.24 technical documentation | 24 | **Low** | README + architecture snippets exist but no CRA Annex V technical file | No `TECHNICAL_FILE.md` |
| G13 | No incident response playbook | 17 | **Low** | No incident response procedure, no playbooks, no 72-hour assessment template | No incident response doc |
| G14 | No Art. 30 self-assessment evidence | 30 | **Low** | No conformity self-assessment, no DoC template | No assessment artifacts |