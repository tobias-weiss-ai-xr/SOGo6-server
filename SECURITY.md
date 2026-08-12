# Security Policy — SOGo6 Server

See the parent repository for the full policy:
https://github.com/tobias-weiss-ai-xr/SOGo6-dockerized/blob/main/SECURITY.md

## Reporting a Vulnerability

**Do not open public issues.** Report privately to the maintainers
(GitHub private vulnerability report in the parent repo). The API serves
`/.well-known/security.txt` and `/security.txt` (RFC 9116) with the
machine-readable policy.

- Acknowledgment: ≤ 48 h
- Fix (HIGH/CRITICAL): target ≤ 30 days
- Coordinated disclosure per CRA Art. 14(2)

## Security features implemented

- **AuthN/AuthZ**: JWT (user + admin), WebAuthn passkeys, MFA/TOTP,
  app passwords, SAML2 SSO, OIDC SSO, brute-force rate limiting
- **Data protection**: AES-256-GCM at-rest encryption, TLS in transit,
  PGP end-to-end mail
- **Integrity**: tamper-evident audit log (hash chain) + SIEM export
- **Supply chain**: dependency pinning (poetry), Trivy scans in CI
  (parent repo), CycloneDX SBOM generation

## Scope

This repository contains the Flask/Python backend. Frontend, mail,
LDAP or database component vulnerabilities are handled by the same
maintainers via the parent repository's policy.
