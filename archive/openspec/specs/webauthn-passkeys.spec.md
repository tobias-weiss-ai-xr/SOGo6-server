# WebAuthn / Passkeys Specification

## 1. Overview

**Feature**: WebAuthn/Passkeys Authentication  
**Status**: ⚠️ Needs Implementation  
**Priority**: Tier 0 (Foundation)  
**Effort**: 3-4 weeks  
**Dependencies**: Existing authentication system (✅ Complete)

WebAuthn enables passwordless authentication using device-based credentials (biometrics, PIN). This spec defines implementation of WebAuthn support in SOGo 6.

---

## 2. Goals

### Primary
- Register passkeys for accounts
- Login with passkeys
- Device management UI
- Multi-device support
- Cross-browser compatibility
- Graceful fallback to passwords

### Secondary
- Conditional MFA (passkey + password)
- Policy enforcement (require passkeys for some users)
- Audit logging
- Recovery options

---

## 3. Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│    API      │───▶│  WebAuthn   │
│  (Browser)  │◀───│  (Server)   │◀───│  Service    │
└─────────────┘    └─────────────┘    └─────────────┘
          │                   │
          ▼                   ▼
┌─────────────┐    ┌─────────────┐
│ WebAuthn API│    │  Database   │
│  (Browser)  │    │ + Redis     │
└─────────────┘    └─────────────┘
```

### Components
- **Backend**: `ApiWebAuthn.py`, `WebAuthnService.py`, models
- **Frontend**: Passkey login, registration, management UI
- **Storage**: PostgreSQL for credentials, Redis for challenges

---

## 4. Data Models

### Database Tables

```sql
-- Credentials
CREATE TABLE webauthn_credentials (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key_cose BYTEA NOT NULL,
    attestation_type VARCHAR(50),
    name VARCHAR(255),
    is_default BOOLEAN DEFAULT FALSE,
    sign_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_created (created_at),
    INDEX idx_user (user_id)
);

-- Challenges
CREATE TABLE webauthn_challenges (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255),
    challenge_type VARCHAR(20) NOT NULL, -- register, login
    challenge BYTEA NOT NULL,
    rp_id VARCHAR(255) NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_expires (expires_at),
    INDEX idx_user (user_id)
);

-- Audit Log
CREATE TABLE webauthn_audit_log (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255),
    action VARCHAR(50) NOT NULL, -- register, login, remove, error
    credential_id VARCHAR(36),
    success BOOLEAN NOT NULL,
    ip_address INET,
    error_code VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_user (user_id),
    INDEX idx_action (action),
    INDEX idx_created (created_at)
);
```

---

## 5. API Design

### User Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user/v1/webauthn/challenge/register` | Get registration challenge |
| POST | `/user/v1/webauthn/register` | Register new passkey |
| GET | `/user/v1/webauthn/challenge/login` | Get login challenge |
| POST | `/user/v1/webauthn/login` | Authenticate with passkey |
| GET | `/user/v1/webauthn/credentials` | List registered passkeys |
| DELETE | `/user/v1/webauthn/credentials/{id}` | Remove passkey |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/v1/webauthn/users` | List users with passkeys |
| GET | `/admin/v1/webauthn/policies` | Get WebAuthn policy |
| POST | `/admin/v1/webauthn/policies` | Set WebAuthn policy |
| GET | `/admin/v1/webauthn/audit` | Get audit log |

---

## 6. Implementation

### WebAuthn Flow (Registration)

1. Client requests registration challenge from server
2. Server generates challenge, stores it, returns options
3. Client calls `navigator.credentials.create()` with options
4. Browser/OS prompts user to create passkey
5. Browser returns credential to client
6. Client sends credential to server
7. Server validates credential, stores it, returns success

### WebAuthn Flow (Authentication)

1. Client requests login challenge from server
2. Server generates challenge, stores it, returns options
3. Client calls `navigator.credentials.get()` with options
4. Browser/OS prompts user for passkey
5. Browser returns assertion to client
6. Client sends assertion to server
7. Server validates assertion, creates session, returns tokens

### Key Implementation Points

**Challenge Generation**:
```python
def generate_challenge(self, user_id, challenge_type):
    challenge = secrets.token_bytes(32)
    expires_at = datetime.now() + timedelta(minutes=5)
    # Store in DB with user_id, challenge_type, rp_id
    return challenge
```

**Credential Verification**:
- Verify challenge matches
- Verify RP ID matches
- Verify signature using COSE public key
- Verify sign count is increasing
- Check user verification flag if required

**Supported Algorithms**:
```
ES256 (-7), ES384 (-35), ES521 (-36), RS256 (-257), 
RS384 (-258), RS512 (-259), PS256 (-37), PS384 (-38), 
PS512 (-39), Ed25519 (-8)
```

### Client-Side (TypeScript)

```typescript
// Check WebAuthn support
const isWebAuthnSupported = () => {
  return 'credentials' in navigator && 
         'PublicKeyCredential' in window;
};

// Register new passkey
const registerPasskey = async (userId: string, userName: string) => {
  const response = await fetch('/user/v1/webauthn/challenge/register', {
    credentials: 'include'
  });
  const { options, request_id } = await response.json();
  
  options.challenge = uint8ArrayToBase64Url(options.challenge);
  options.user.id = uint8ArrayToBase64Url(options.user.id);
  
  const credential = await navigator.credentials.create({
    publicKey: options
  });
  
  const attestationResponse = {
    id: credential.id,
    rawId: arrayBufferToBase64Url(credential.rawId),
    type: credential.type,
    response: {
      attestationObject: arrayBufferToBase64Url(credential.response.attestationObject),
      clientDataJSON: arrayBufferToBase64Url(credential.response.clientDataJSON)
    },
    request_id
  };
  
  const registerResponse = await fetch('/user/v1/webauthn/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(attestationResponse),
    credentials: 'include'
  });
  
  return registerResponse.json();
};

// Login with passkey
const loginWithPasskey = async (userId?: string) => {
  const response = await fetch('/user/v1/webauthn/challenge/login', {
    credentials: 'include'
  });
  const { options, request_id } = await response.json();
  
  options.challenge = uint8ArrayToBase64Url(options.challenge);
  options.allowCredentials.forEach(c => {
    c.id = uint8ArrayToBase64Url(c.id);
  });
  
  const assertion = await navigator.credentials.get({
    publicKey: options
  });
  
  const assertionResponse = {
    id: assertion.id,
    rawId: arrayBufferToBase64Url(assertion.rawId),
    type: assertion.type,
    response: {
      authenticatorData: arrayBufferToBase64Url(assertion.response.authenticatorData),
      clientDataJSON: arrayBufferToBase64Url(assertion.response.clientDataJSON),
      signature: arrayBufferToBase64Url(assertion.response.signature),
      userHandle: assertion.response.userHandle ? 
                  arrayBufferToBase64Url(assertion.response.userHandle) : null
    },
    request_id
  };
  
  const loginResponse = await fetch('/user/v1/webauthn/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(assertionResponse),
    credentials: 'include'
  });
  
  return loginResponse.json();
};
```

---

## 7. Security Considerations

### Requirements
- ✅ Use HTTPS (WebAuthn requires secure context)
- ✅ Validate challenge exactly once
- ✅ Verify RP ID matches origin
- ✅ Verify signature cryptographically
- ✅ Check sign count to prevent cloning
- ✅ Rate limit registration attempts
- ✅ Store private keys securely (they're in COSE public key format only)

### Best Practices
- Store challenges short-lived (5-10 minutes)
- Clean up expired challenges regularly
- Log all passkey operations for audit
- Prevent duplicate credential IDs
- Require user verification for sensitive operations
- Support backup/restore via OS/browser sync

---

## 8. UI Integration

### Login Page
```
┌─────────────────────────────────┐
│        Sign In                  │
├─────────────────────────────────┤
│  username@example.com           │
│  ┌─────────────────────────────┐│
│  │ 🔑 Sign in with passkey    │←▶│  -- Primary button
│  └─────────────────────────────┘│
│  OR                              │
│  ┌─────────────────────────────┐│
│  │ 🔒 Sign in with password   │←▶│  -- Fallback
│  └─────────────────────────────┘│
│                                 │
│  [x] Remember me                │
│  Forgot password?               │
└─────────────────────────────────┘
```

### Settings - Passkeys
```
┌─────────────────────────────────┐
│ Security > Passkeys             │
├─────────────────────────────────┤
│ Add new passkey                 │
│ ┌──────────────────────────────┐ │
│ │ 📱 iPhone 15 Pro (Face ID)   │ │
│ │ Last used: 2 minutes ago     │ │
│ │ Default ✓                   │ │
│ │ [Rename] [Remove]            │ │
│ ├──────────────────────────────┤ │
│ │ 💻 MacBook Pro (Touch ID)    │ │
│ │ Last used: Yesterday         │ │
│ │ [Rename] [Remove]            │ │
│ ├──────────────────────────────┤ │
│ │ 🔑 YubiKey 5 NFC             │ │
│ │ Last used: 3 days ago        │ │
│ │ [Rename] [Remove]            │ │
│ └──────────────────────────────┘ │
│                                 │
│ Note: Passkeys sync across your │
│ devices via your operating      │
│ system's password manager.      │
└─────────────────────────────────┘
```

---

## 9. Browser Support

| Browser | WebAuthn | Passkey Sync | Notes |
|---------|----------|--------------|-------|
| Chrome | ✅ 80+ | ✅ | Full support |
| Firefox | ✅ 60+ | ✅ | Full support |
| Safari | ✅ 14+ | ✅ | Full support |
| Edge | ✅ 80+ | ✅ | Full support |
| Chrome Android | ✅ | ✅ | Full support |
| Safari iOS | ✅ 14+ | ✅ | Full support |

**Note**: All modern browsers support WebAuthn. Mobile browsers require OS-level support.

---

## 10. Implementation Plan

### Phase 1: Backend (Week 1)
- Create database schema
- Implement `WebAuthnService.py`
- Implement challenge generation and validation
- Implement `ApiWebAuthn.py` endpoints
- Write unit tests

### Phase 2: Frontend (Week 2)
- Create passkey login component
- Create passkey registration component
- Create passkey management page
- Add WebAuthn support detection
- Add fallback to password

### Phase 3: Integration (Week 3)
- Integrate with existing auth flow
- Add session management
- Add rate limiting
- Add audit logging
- Configure RP ID

### Phase 4: Testing & Polish (Week 4)
- End-to-end testing on all browsers
- Cross-device testing
- Security testing
- Documentation
- User testing

---

## 11. Configuration

```bash
# WebAuthn Settings
SOGO_WEBAUTHN_ENABLED=true
SOGO_WEBAUTHN_RP_ID=example.com
SOGO_WEBAUTHN_RP_NAME="SOGo6"
SOGO_WEBAUTHN_ORIGIN=https://mail.example.com
SOGO_WEBAUTHN_TIMEOUT=60000
SOGO_WEBAUTHN_USER_VERIFICATION=preferred
SOGO_WEBAUTHN_ALLOW_PASSWORD_FALLBACK=true
SOGO_WEBAUTHN_REQUIRE_PASSKEY=false
```

---

## 12. Success Criteria

- [ ] Passkey registration works on all supported browsers
- [ ] Passkey login works on all supported browsers
- [ ] Users can manage passkeys in settings
- [ ] Multiple devices per user supported
- [ ] Graceful fallback to password
- [ ] Audit logging for all operations
- [ ] Rate limiting to prevent brute force
- [ ] Cross-origin protection (RP ID validation)
- [ ] >90% test coverage
- [ ] Complete documentation

---

## 13. References

### Standards
- [W3C WebAuthn](https://www.w3.org/TR/webauthn-2/) - Main specification
- [W3C WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/) - Latest version
- [FIDO2](https://fidoalliance.org/specifications/fido-v2.0-id-20180227/fido-client-to-authenticator-protocol-v2.0-id-20180227.html) - CTAP
- [COSE](https://tools.ietf.org/html/rfc8152) - CBOR Object Signing and Encryption
- [CBOR](https://tools.ietf.org/html/rfc7049) - Concise Binary Object Representation

### Libraries
- [python-webauthn](https://github.com/duo-labs/py_webauthn) - WebAuthn for Python (reference)
- [@simplewebauthn/browser](https://github.com/MasterKale/SimpleWebAuthn) - Browser library
- [@simplewebauthn/server](https://github.com/MasterKale/SimpleWebAuthn) - Server library

### Guides
- [WebAuthn.io](https://webauthn.io/) - Demo and explanation
- [MDN WebAuthn](https://developer.mozilla.org/en-US/docs/Web/API/WebAuthn_API) - MDN documentation
- [Google WebAuthn Guide](https://developers.google.com/identity/fido) - Google's guide
- [Apple Passkeys](https://developer.apple.com/passkeys/) - Apple documentation

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| WebAuthn | Web Authentication API - browser API for public key auth |
| Passkey | User-friendly name for discoverable WebAuthn credential |
| RP | Relying Party - the website/application (us) |
| Authenticator | Device that stores credentials (phone, security key) |
| Attestation | Proof that credential was created on a genuine device |
| COSE | CBOR Object Signing and Encryption - format for public keys |
| CBOR | Concise Binary Object Representation - binary JSON alternative |
| AAGUID | Authenticator Attestation GUID - device manufacturer identifier |
| Sign Count | Counter to prevent credential cloning |

---

## Appendix B: Policy Settings

```python
class WebAuthnPolicy:
    enabled: bool = True
    
    # RP Configuration
    rp_id: str = "example.com"
    rp_name: str = "SOGo6"
    origin: str = "https://mail.example.com"
    
    # Security
    user_verification: str = "preferred"  # required, preferred, discouraged
    authenticator_attachment: str = None  # platform, cross-platform, or None (any)
    require_resident_key: bool = True
    
    # Algorithms
    algorithms: list = [-7, -257, -258, -259, -37, -38, -39, -8]
    
    # Limits
    timeout: int = 60000  # milliseconds
    max_credentials_per_user: int = 10
    
    # Rate Limiting
    rate_limit_attempts: int = 5
    rate_limit_window: int = 300  # seconds
    
    # Behavior
    allow_password_fallback: bool = True
    require_passkey: bool = False
    force_passkey_groups: list = []
```

---

## Appendix C: Error Codes

```
┌─────────────────┬─────────────────┬─────────────────────┐
│   Error Code     │ HTTP Status     │   Description        │
├─────────────────┼─────────────────┼─────────────────────┤
│ INVALID_CHALLENGE│ 400             │ Challenge invalid   │
│ CHALLENGE_EXPIRED│ 400             │ Challenge expired   │
│ CHALLENGE_USED   │ 400             │ Challenge reused    │
│ INVALID_ORIGIN   │ 400             │ Origin mismatch     │
│ INVALID_SIGNATURE│ 400             │ Signature invalid   │
│ INVALID_SIGN_COUNT│400            │ Sign count issue    │
│ CREDENTIAL_EXISTS│ 409             │ Already registered  │
│ CREDENTIAL_NOT_FOUND│404           │ Not registered      │
│ USER_VERIFICATION_REQUIRED│400│ UV not satisfied │
│ RATE_LIMITED     │ 429             │ Too many attempts   │
│ NOT_SUPPORTED    │ 400             │ Browser doesn't support│
└─────────────────┴─────────────────┴─────────────────────┘
```

---

**Document Status**: 📋 Draft / Specified  
**Author**: Tobias Weiss (@tobias-weiss-ai-xr)  
**Created**: 2025-08-20  
**Last Modified**: 2025-08-20  
**Target Implementation**: Q3-Q4 2025
