# DKIM, DMARC, and SPF Wizard Specification

## Overview

This specification defines the **DKIM/DMARC/SPF Wizard** feature for SOGo 6, providing administrators with an easy-to-use interface for configuring email authentication protocols. This feature helps prevent email spoofing, phishing, and improves deliverability.

**Status**: ⚠️ Needs Implementation
**Version**: 1.0.0
**Priority**: Tier 0 (Foundation)
**Effort**: Low-Medium (2-3 weeks)
**Dependencies**: None (standalone feature)

---

## Table of Contents

1. [Background](#background)
2. [Goals](#goals)
3. [Features](#features)
4. [Architecture](#architecture)
5. [API Design](#api-design)
6. [Implementation Details](#implementation-details)
7. [Implementation Plan](#implementation-plan)
8. [Testing](#testing)

---

## Background

### Problem

Email authentication is critical for:
- **Preventing spoofing**: Ensure emails appear to come from who they claim
- **Improving deliverability**: ISPs increasingly require authentication
- **Compliance**: Many regulations require email authentication
- **Brand protection**: Prevent attackers from impersonating the domain

### Current State

SOGo 6 currently has:
- SMTP server (Stalwart) that **supports** DKIM, DMARC, SPF
- No admin UI for configuring these protocols
- Manual DNS record creation required
- No validation of existing records
- No monitoring of authentication results

### Effects

Without proper configuration:
- Emails may be rejected or marked as spam
- No protection against impersonation
- Difficult to troubleshoot deliverability issues
- Time-consuming manual setup

---

## Goals

### Primary Goals

1. **DNS Record Generator**: Generate valid DKIM, DMARC, SPF records
2. **DNS Validation**: Validate existing DNS records
3. **Configuration Wizard**: Step-by-step setup guide
4. **Best Practices Guide**: Recommend optimal configurations
5. **Monitoring Dashboard**: Show authentication results
6. **Troubleshooting**: Help diagnose configuration issues

### Secondary Goals

1. **Multi-Domain Support**: Manage multiple domains
2. **Bulk Operations**: Configure multiple domains at once
3. **Import/Export**: Save and restore configurations
4. **History**: Track configuration changes over time
5. **Integration**: Link with certificate management

---

## Features

### Core Features (Must Have)

#### DKIM (DomainKeys Identified Mail)
- [ ] Generate DKIM key pairs (RSA 1024/2048/4096 bits)
- [ ] Generate DNS TXT record for public key
- [ ] Configure selector names (default: `default`, `sogo6`)
- [ ] Store private keys securely
- [ ] Rotate DKIM keys
- [ ] Validate existing DKIM records
- [ ] Test DKIM signing

#### DMARC (Domain-based Message Authentication, Reporting & Conformance)
- [ ] Generate DMARC policy record
- [ ] Configure policy (none, quarantine, reject)
- [ ] Set percentage (pct) for gradual rollout
- [ ] Configure subdomain policy (sp)
- [ ] Set alignment (aspf, adkim) - strict or relaxed
- [ ] Add reporting addresses (rua, ruf)
- [ ] Validate existing DMARC records
- [ ] Generate aggregation reports

#### SPF (Sender Policy Framework)
- [ ] Generate SPF record
- [ ] Include common providers (Google, Microsoft, etc.)
- [ ] Add IP addresses and ranges
- [ ] Add MX records
- [ ] Add A records
- [ ] Add include statements
- [ ] Validate existing SPF records
- [ ] Check SPF lookup limits (< 10)
- [ ] Test SPF validation

#### Configuration Management
- [ ] Domain list with authentication status
- [ ] Per-domain configuration
- [ ] Enable/disable protocols per domain
- [ ] Copy configuration between domains
- [ ] Reset to defaults

#### Validation and Testing
- [ ] Validate all DNS records (DKIM, DMARC, SPF)
- [ ] Check DNS propagation
- [ ] Test actual email sending with authentication
- [ ] Verify alignment (DKIM/SPF with From domain)
- [ ] Detect configuration issues and warnings

### Advanced Features (Nice to Have)

#### Multi-Domain Management
- [ ] Bulk configure multiple domains
- [ ] Domain templates
- [ ] Wildcard domain support
- [ ] Subdomain management
- [ ] Domain groups

#### Monitoring and Reporting
- [ ] Authentication result dashboard
- [ ] DMARC aggregate report parsing
- [ ] DMARC forensic report parsing
- [ ] Failed authentication alerts
- [ ] Deliverability metrics
- [ ] Export reports to CSV/PDF

#### Advanced Configuration
- [ ] Custom key storage locations
- [ ] External key management integration
- [ ] Multiple selectors per domain
- [ ] Key rollover automation
- [ ] Backup and restore configurations

#### Integration
- [ ] Let's Encrypt integration (for DANE)
- [ ] MTA-STS configuration
- [ ] TLS-RPT configuration
- [ ] BIMI (Brand Indicators for Message Identification)
- [ ] API for external tools

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Interface                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Admin Panel                              │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │ │
│  │  │  Dashboard   │  │  Domain List │  │  Domain      │     │ │
│  │  │              │  │              │  │  Config     │     │ │
│  │  │ - Overall    │  │ - All        │  │ - DKIM      │     │ │
│  │  │   status     │  │   domains    │  │ - DMARC     │     │ │
│  │  │ - Quick stats│  │ - Search     │  │ - SPF       │     │ │
│  │  │ - Warnings   │  │ - Bulk ops   │  │ - Test      │     │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend Services                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    API Layer                                  │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │ │
│  │  │ DKIM API     │  │ DMARC API    │  │ SPF API      │     │ │
│  │  │              │  │              │  │              │     │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │ │
│  │         │                  │                  │            │ │
│  └─────────┼──────────────────┼──────────────────┼────────────┘ │
│            │                  │                  │              │
│            ▼                  ▼                  ▼              │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Service Layer                             │ │
│  │  ┌──────────────────────┐                                  │ │
│  │  │ AuthConfigService    │                                  │ │
│  │  │                      │                                  │ │
│  │  │  - DKIM Management   │                                  │ │
│  │  │  - DMARC Management  │                                  │ │
│  │  │  - SPF Management    │                                  │ │
│  │  │  - DNS Validation    │                                  │ │
│  │  │  - Testing           │                                  │ │
│  │  └──────────────────────┘                                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Storage                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │ File System  │  │ SMTP Server  │      │
│  │              │  │              │  │ (Stalwart)   │      │
│  │ - domains    │  │ - DKIM keys │  │ - Config     │      │
│  │ - dkim_keys  │  │ - Certs      │  │              │      │
│  │ - dmarc_pols │  │              │  │              │      │
│  │ - spf_recs   │  │              │  │              │      │
│  │ - reports    │  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    External DNS                                  │
├─────────────────────────────────────────────────────────────────┤
│  DNS Providers (query for validation and publishing)              │
└─────────────────────────────────────────────────────────────────┘
```

### Component Directory Structure

```
sogo6-server/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── admin/
│   │           ├── ApiDKIM.py                    # NEW
│   │           ├── ApiDMARC.py                   # NEW
│   │           ├── ApiSPF.py                      # NEW
│   │           └── ApiEmailAuth.py                # NEW: Combined API
│   ├── service/
│   │   ├── DKIMService.py                        # NEW
│   │   ├── DMARCService.py                       # NEW
│   │   ├── SPFService.py                         # NEW
│   │   └── EmailAuthService.py                   # NEW: Main service
│   └── model/
│       └── admin/
│           ├── DKIMKey.py                        # NEW
│           ├── DMARCPolicy.py                    # NEW
│           └── SPFRecord.py                      # NEW

# Key Storage (secure)
└── /var/lib/sogo6/dkim/
    ├── keys/           # Private keys
    │   └── {domain}.
    │       └── {selector}.key
    └── configs/        # Configurations
        └── {domain}.json

# Frontend (sogo6-ui)
sogo6-ui/
└── src/
    ├── features/
    │   └── admin/
    │       └── email-authentication/              # NEW
    │           ├── index.tsx
    │           ├── components/
    │           │   ├── Dashboard.tsx
    │           │   ├── DomainList.tsx
    │           │   ├── DomainConfig.tsx
    │           │   ├── DKIMConfig.tsx
    │           │   ├── DMARCConfig.tsx
    │           │   ├── SPFConfig.tsx
    │           │   ├── RecordValidator.tsx
    │           │   ├── TestSender.tsx
    │           │   └── ReportViewer.tsx
    │           └── store/
    │               ├── dkim-api.ts
    │               ├── dmarc-api.ts
    │               └── spf-api.ts
    └── app/
        └── [locale]/(loggedin)/admin/
            └── email-authentication/
                └── page.tsx
```

---

## API Design

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/v1/email-auth/domains` | List all configured domains |
| POST | `/admin/v1/email-auth/domains` | Add domain |
| DELETE | `/admin/v1/email-auth/domains/{domain}` | Remove domain |
| GET | `/admin/v1/email-auth/domains/{domain}/status` | Get authentication status |
| GET | `/admin/v1/email-auth/dkim` | List DKIM configurations |
| POST | `/admin/v1/email-auth/dkim/generate` | Generate DKIM key pair |
| POST | `/admin/v1/email-auth/dkim/{domain}` | Configure DKIM for domain |
| GET | `/admin/v1/email-auth/dkim/{domain}` | Get DKIM config |
| PUT | `/admin/v1/email-auth/dkim/{domain}` | Update DKIM config |
| DELETE | `/admin/v1/email-auth/dkim/{domain}` | Remove DKIM config |
| POST | `/admin/v1/email-auth/dkim/{domain}/rotate` | Rotate DKIM keys |
| POST | `/admin/v1/email-auth/dkim/{domain}/validate` | Validate DKIM DNS |
| GET | `/admin/v1/email-auth/dmarc` | List DMARC policies |
| POST | `/admin/v1/email-auth/dmarc/{domain}` | Configure DMARC for domain |
| GET | `/admin/v1/email-auth/dmarc/{domain}` | Get DMARC policy |
| PUT | `/admin/v1/email-auth/dmarc/{domain}` | Update DMARC policy |
| DELETE | `/admin/v1/email-auth/dmarc/{domain}` | Remove DMARC policy |
| POST | `/admin/v1/email-auth/dmarc/{domain}/validate` | Validate DMARC DNS |
| GET | `/admin/v1/email-auth/dmarc/{domain}/reports` | Get DMARC reports |
| GET | `/admin/v1/email-auth/spf` | List SPF records |
| POST | `/admin/v1/email-auth/spf/{domain}` | Configure SPF for domain |
| GET | `/admin/v1/email-auth/spf/{domain}` | Get SPF record |
| PUT | `/admin/v1/email-auth/spf/{domain}` | Update SPF record |
| DELETE | `/admin/v1/email-auth/spf/{domain}` | Remove SPF record |
| POST | `/admin/v1/email-auth/spf/{domain}/validate` | Validate SPF DNS |
| POST | `/admin/v1/email-auth/test` | Test email authentication |
| POST | `/admin/v1/email-auth/validate-all` | Validate all domain records |

### Request/Response Schemas

#### Domain Schema

```python
from marshmallow import Schema, fields, validate
from typing import Optional, List

class DomainAuthStatusSchema(Schema):
    """Authentication status for a domain."""
    domain = fields.String(required=True)
    dkim_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    dkim_status_msg = fields.String()
    dmarc_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    dmarc_status_msg = fields.String()
    spf_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    spf_status_msg = fields.String()
    overall_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    overall_recommendations = fields.List(fields.String())


class DomainSchema(Schema):
    """Domain configuration."""
    name = fields.String(required=True)
    description = fields.String(load_default="")
    is_active = fields.Boolean(load_default=True)
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')
```

#### DKIM Schema

```python
class DKIMKeyPairSchema(Schema):
    """DKIM key pair (private key is sensitive)."""
    domain = fields.String(required=True)
    selector = fields.String(required=True, load_default="default")
    public_key = fields.String(required=True)
    private_key = fields.String(required=True)  # Only in response, masked in logs
    key_length = fields.Integer(required=True, validate=validate.OneOf([1024, 2048, 4096]))
    key_type = fields.String(load_default="rsa")
    dns_record = fields.String(required=True)  # Full TXT record for DNS
    created_at = fields.DateTime(format='iso')


class DKIMConfigSchema(Schema):
    """DKIM configuration for a domain."""
    domain = fields.String(required=True)
    selector = fields.String(load_default="default")
    enabled = fields.Boolean(load_default=True)
    key_length = fields.Integer(load_default=2048, validate=validate.OneOf([1024, 2048, 4096]))
    signing_algorithm = fields.String(load_default="rsa-sha256", 
                                      validate=validate.OneOf(["rsa-sha1", "rsa-sha256"]))
    headers_to_sign = fields.List(
        fields.String(),
        load_default=None,
        metadata={"description": "Headers to sign, null = all"}
    )
    use_domainkeys = fields.Boolean(load_default=False)
    use_adsp = fields.Boolean(load_default=False)
    notes = fields.String(load_default="")
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')


class DKIMValidationResultSchema(Schema):
    """DKIM DNS validation result."""
    domain = fields.String(required=True)
    selector = fields.String(required=True)
    is_valid = fields.Boolean(required=True)
    errors = fields.List(fields.String(), load_default=None)
    warnings = fields.List(fields.String(), load_default=None)
    dns_record_found = fields.Boolean(required=True)
    record_value = fields.String(load_default=None)
    expected_value = fields.String(required=True)
    checked_at = fields.DateTime(format='iso')
```

#### DMARC Schema

```python
class DMARCPolicySchema(Schema):
    """DMARC policy configuration."""
    domain = fields.String(required=True)
    enabled = fields.Boolean(load_default=True)
    
    # Policy
    policy = fields.String(
        load_default="none",
        validate=validate.OneOf(["none", "quarantine", "reject"]),
        metadata={"description": "Policy for failed emails"}
    )
    
    # Subdomain policy
    subdomain_policy = fields.String(
        load_default=None,
        validate=validate.OneOf(["none", "quarantine", "reject"]),
        metadata={"description": "Policy for subdomains, null = same as policy"}
    )
    
    # Percentage (for gradual rollout)
    pct = fields.Integer(
        load_default=100,
        validate=validate.Range(min=1, max=100),
        metadata={"description": "Percentage of emails to apply policy to"}
    )
    
    # Alignment
    aspf = fields.String(
        load_default="r",
        validate=validate.OneOf(["r", "s"]),
        metadata={"description": "SPF alignment: r=relaxed, s=strict"}
    )
    adkim = fields.String(
        load_default="r",
        validate=validate.OneOf(["r", "s"]),
        metadata={"description": "DKIM alignment: r=relaxed, s=strict"}
    )
    
    # Reporting
    rua = fields.List(
        fields.Email(),
        load_default=None,
        metadata={"description": "Aggregate report URIs (mailto: addresses)"}
    )
    ruf = fields.List(
        fields.Email(),
        load_default=None,
        metadata={"description": "Forensic report URIs"}
    )
    ri = fields.Integer(
        load_default=86400,
        validate=validate.Range(min=1),
        metadata={"description": "Report interval in seconds"}
    )
    
    notes = fields.String(load_default="")
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')


class DMARCValidationResultSchema(Schema):
    """DMARC DNS validation result."""
    domain = fields.String(required=True)
    is_valid = fields.Boolean(required=True)
    errors = fields.List(fields.String(), load_default=None)
    warnings = fields.List(fields.String(), load_default=None)
    dns_record_found = fields.Boolean(required=True)
    record_value = fields.String(load_default=None)
    expected_record = fields.String(required=True)
    checked_at = fields.DateTime(format='iso')
```

#### SPF Schema

```python
class SPFRecordSchema(Schema):
    """SPF record configuration."""
    domain = fields.String(required=True)
    enabled = fields.Boolean(load_default=True)
    
    # Record parts
    version = fields.String(load_default="v=spf1")
    
    # Mechanisms
    include_mechanisms = fields.List(fields.String(), load_default=None)
    ip4_mechanisms = fields.List(fields.String(), load_default=None)
    ip6_mechanisms = fields.List(fields.String(), load_default=None)
    a_mechanisms = fields.List(fields.String(), load_default=None)
    mx_mechanisms = fields.List(fields.String(), load_default=None)
    ptr_mechanisms = fields.List(fields.String(), load_default=None)
    exists_mechanisms = fields.List(fields.String(), load_default=None)
    
    # Qualifiers (optional, default is +)
    # Mechanism format: "[qualifier]type[:value]"
    # where qualifier is +, -, ~, ?
    raw_mail_servers = fields.String(
        load_default=None,
        metadata={"description": "Raw SPF mechanisms with qualifiers"}
    )
    
    # All Qualifier
    all_qualifier = fields.String(
        load_default="-all",
        validate=validate.OneOf(["+all", "-all", "~all", "?all"])
    )
    
    # Modifiers
    redirect_modifier = fields.String(load_default=None)
    explanation_modifier = fields.String(load_default=None)
    
    notes = fields.String(load_default="")
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')


class SPFValidationResultSchema(Schema):
    """SPF DNS validation result."""
    domain = fields.String(required=True)
    is_valid = fields.Boolean(required=True)
    errors = fields.List(fields.String(), load_default=None)
    warnings = fields.List(fields.String(), load_default=None)
    dns_record_found = fields.Boolean(required=True)
    record_value = fields.String(load_default=None)
    expected_record = fields.String(required=True)
    mechanism_count = fields.Integer()
    dns_lookup_count = fields.Integer()
    over_lookup_limit = fields.Boolean()
    checked_at = fields.DateTime(format='iso')
```

#### Test Schema

```python
class TestEmailAuthSchema(Schema):
    """Request to test email authentication."""
    from_address = fields.Email(required=True)
    to_address = fields.Email(load_default=None)
    domain = fields.String(required=True)
    smtp_server = fields.String(load_default=None)
    

class TestEmailAuthResultSchema(Schema):
    """Result of authentication test."""
    test_id = fields.String()
    from_address = fields.Email()
    domain = fields.String()
    timestamp = fields.DateTime(format='iso')
    
    # Results
    spf_result = fields.String(validate=validate.OneOf(["pass", "fail", "softfail", "neutral", "temperror", "permerror", "none"]))
    spf_explanation = fields.String()
    dkim_result = fields.String(validate=validate.OneOf(["pass", "fail", "neutral", "temperror", "permerror", "none"]))
    dkim_explanation = fields.String()
    dkim_selector = fields.String()
    dmarc_result = fields.String(validate=validate.OneOf(["pass", "fail", "none"]))
    dmarc_explanation = fields.String()
    dmarc_alignment_spf = fields.String()
    dmarc_alignment_dkim = fields.String()
    
    # Overall
    overall_result = fields.String()
    is_deliverable = fields.Boolean()
    recommendations = fields.List(fields.String())
    
    # Server info
    smtp_server = fields.String()
    smtp_response = fields.String()
```

---

## Implementation Details

### DKIM Implementation

**Key Generation:**
```python
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import base64

def generate_dkim_key_pair(key_length=2048):
    """Generate DKIM RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_length
    )
    
    public_key = private_key.public_key()
    
    # Serialize public key for DNS
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    # Base64 encode and remove headers/footers/whitespace
    public_key_b64 = base64.b64encode(public_key_bytes).decode('utf-8')
    public_key_b64 = public_key_b64.replace('\n', '')
    
    # Private key in PEM format
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    return {
        'private_key': private_key_pem,
        'public_key': public_key_b64
    }

def generate_dkim_dns_record(domain, selector, public_key_b64):
    """Generate DKIM DNS TXT record."""
    record = f'v=DKIM1; k=rsa; p={public_key_b64}'
    return record
```

**Key Storage:**
```python
class DKIMKeyStorage:
    """Secure storage for DKIM private keys."""
    
    def __init__(self, storage_path='/var/lib/sogo6/dkim/keys'):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def save_key(self, domain, selector, private_key, public_key):
        """Save DKIM key pair."""
        # Create domain directory
        domain_dir = self.storage_path / domain
        domain_dir.mkdir(exist_ok=True)
        
        # Save private key (with restricted permissions)
        key_file = domain_dir / f'{selector}.key'
        key_file.write_bytes(private_key.encode('utf-8'))
        key_file.chmod(0o600)  # Read/write only by owner
        
        # Save metadata
        meta_file = domain_dir / f'{selector}.json'
        meta_file.write_json({
            'domain': domain,
            'selector': selector,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'public_key_hash': hashlib.sha256(public_key.encode()).hexdigest()
        })
    
    def load_key(self, domain, selector):
        """Load DKIM private key."""
        key_file = self.storage_path / domain / f'{selector}.key'
        if not key_file.exists():
            raise FileNotFoundError(f'DKIM key not found: {domain}/{selector}')
        return key_file.read_bytes().decode('utf-8')
    
    def list_keys(self, domain):
        """List all selectors for a domain."""
        domain_dir = self.storage_path / domain
        if not domain_dir.exists():
            return []
        return [f.stem for f in domain_dir.glob('*.key')]
    
    def delete_key(self, domain, selector):
        """Delete DKIM key."""
        key_file = self.storage_path / domain / f'{selector}.key'
        meta_file = self.storage_path / domain / f'{selector}.json'
        
        if key_file.exists():
            key_file.unlink()
        if meta_file.exists():
            meta_file.unlink()
```

**DNS Validation:**
```python
import dns.resolver

def validate_dkim_dns(domain, selector):
    """Validate DKIM DNS record."""
    try:
        # Lookup TXT record for selector._domainkeys.domain
        fqdn = f'{selector}._domainkeys.{domain}'
        answers = dns.resolver.resolve(fqdn, 'TXT')
        
        record = answers[0].strings[0].decode('utf-8')
        
        return {
            'is_valid': True,
            'dns_record_found': True,
            'record_value': record,
            'errors': [],
            'warnings': []
        }
    except dns.resolver.NoAnswer:
        return {
            'is_valid': False,
            'dns_record_found': False,
            'record_value': None,
            'errors': [f'No TXT record found for {selector}._domainkeys.{domain}'],
            'warnings': []
        }
    except Exception as e:
        return {
            'is_valid': False,
            'dns_record_found': False,
            'record_value': None,
            'errors': [f'DNS lookup failed: {str(e)}'],
            'warnings': []
        }
```

### DMARC Implementation

**Policy Generation:**
```python
def generate_dmarc_record(policy_config):
    """Generate DMARC DNS TXT record."""
    parts = []
    
    # Version
    parts.append('v=DMARC1')
    
    # Policy
    parts.append(f'p={policy_config.get("policy", "none")}')
    
    # Subdomain policy
    if policy_config.get('subdomain_policy'):
        parts.append(f'sp={policy_config["subdomain_policy"]}')
    
    # Percentage
    parts.append(f'pct={policy_config.get("pct", 100)}')
    
    # Alignment
    parts.append(f'aspf={policy_config.get("aspf", "r")}')
    parts.append(f'adkim={policy_config.get("adkim", "r")}')
    
    # Reporting
    if policy_config.get('rua'):
        for addr in policy_config['rua']:
            parts.append(f'rua={addr}')
    
    if policy_config.get('ruf'):
        for addr in policy_config['ruf']:
            parts.append(f'ruf={addr}')
    
    if policy_config.get('ri'):
        parts.append(f'ri={policy_config["ri"]}')
    
    # Notes
    if policy_config.get('notes'):
        # DMARC allows comments with semicolon prefix
        parts.append(f'p={policy_config["notes"].replace(" ", "_")}')
    
    return '; '.join(parts)
```

**Report Parsing:**
```python
import xml.etree.ElementTree as ET
import gzip
import io

class DMARCAggregateReportParser:
    """Parse DMARC aggregate reports (XML)."""
    
    def parse_report(self, report_email):
        """Parse DMARC aggregate report from email attachment."""
        # Extract attachment from email
        attachment = self._extract_attachment(report_email)
        
        # Decompress if gzipped
        if attachment.name.endswith('.gz'):
            data = gzip.decompress(attachment.content)
        else:
            data = attachment.content
        
        # Parse XML
        xml_content = data.decode('utf-8')
        try:
            root = ET.fromstring(xml_content)
            return self._parse_xml(root)
        except ET.ParseError as e:
            raise ValueError(f'Invalid XML in DMARC report: {e}')
    
    def _parse_xml(self, root):
        """Parse XML structure."""
        report = {
            'report_metadata': self._parse_report_metadata(root.find('report_metadata')),
            'policy_published': self._parse_policy_published(root.find('policy_published')),
            'records': []
        }
        
        for record in root.findall('record'):
            report['records'].append(self._parse_record(record))
        
        return report
    
    def _parse_report_metadata(self, element):
        """Parse report_metadata element."""
        return {
            'org_name': element.find('org_name').text if element is not None else None,
            'email': element.find('email').text if element is not None else None,
            'extra_contact_info': element.find('extra_contact_info').text if element is not None else None,
            'report_id': element.find('report_id').text if element is not None else None,
            'date_range': {
                'begin': int(element.find('date_range/begin').text) if element is not None else None,
                'end': int(element.find('date_range/end').text) if element is not None else None
            },
            'error': element.find('error').text if element is not None else None
        }
    
    def _parse_policy_published(self, element):
        """Parse policy_published element."""
        if element is None:
            return None
        
        policy = {
            'domain': element.find('domain').text,
            'adkim': element.find('adkim').text,
            'aspf': element.find('aspf').text,
            'p': element.find('p').text,
            'sp': element.find('sp').text,
            'pct': int(element.find('pct').text)
        }
        
        # Parse max_age if present
        max_age = element.find('max_age')
        if max_age is not None:
            policy['max_age'] = int(max_age.text)
        
        return policy
    
    def _parse_record(self, element):
        """Parse record element."""
        return {
            'row': {
                'source_ip': element.find('row/source_ip').text,
                'count': int(element.find('row/count').text),
                'policy_evaluated': self._parse_policy_evaluated(element.find('row/policy_evaluated'))
            },
            'identifiers': self._parse_identifiers(element.find('identifiers')),
            'auth_results': self._parse_auth_results(element.find('auth_results'))
        }
    
    def _parse_policy_evaluated(self, element):
        """Parse policy_evaluated element."""
        if element is None:
            return None
        
        return {
            'disposition': element.find('disposition').text,
            'dkim': element.find('dkim').text,
            'spf': element.find('spf').text
        }
    
    def _parse_identifiers(self, element):
        """Parse identifiers element."""
        if element is None:
            return None
        
        return {
            'header_from': element.find('header_from').text
        }
    
    def _parse_auth_results(self, element):
        """Parse auth_results element."""
        if element is None:
            return None
        
        results = {
            'dkim': [],
            'spf': []
        }
        
        for dkim in element.findall('dkim'):
            results['dkim'].append({
                'domain': dkim.find('domain').text,
                'selector': dkim.find('selector').text,
                'result': dkim.find('result').text
            })
        
        for spf in element.findall('spf'):
            results['spf'].append({
                'domain': spf.find('domain').text,
                'scope': spf.find('scope').text,
                'result': spf.find('result').text
            })
        
        return results
```

### SPF Implementation

**Record Generation:**
```python
def generate_spf_record(spf_config):
    """Generate SPF DNS TXT record."""
    parts = []
    
    # Version
    parts.append('v=spf1')
    
    # Process raw mechanisms if provided
    if spf_config.get('raw_mail_servers'):
        parts.extend(spf_config['raw_mail_servers'].split())
    else:
        # Add mechanisms from individual fields
        if spf_config.get('include_mechanisms'):
            for include in spf_config['include_mechanisms']:
                parts.append(f'include:{include}')
        
        if spf_config.get('ip4_mechanisms'):
            for ip in spf_config['ip4_mechanisms']:
                parts.append(f'ip4:{ip}')
        
        if spf_config.get('ip6_mechanisms'):
            for ip in spf_config['ip6_mechanisms']:
                parts.append(f'ip6:{ip}')
        
        if spf_config.get('a_mechanisms'):
            for domain in spf_config['a_mechanisms']:
                parts.append(f'a:{domain}')
        
        if spf_config.get('mx_mechanisms'):
            for domain in spf_config['mx_mechanisms']:
                parts.append(f'mx:{domain}')
    
    # All mechanism
    parts.append(spf_config.get('all_qualifier', '-all'))
    
    # Modifiers
    if spf_config.get('redirect_modifier'):
        parts.append(f'redirect={spf_config["redirect_modifier"]}')
    
    if spf_config.get('explanation_modifier'):
        parts.append(f'explanation={spf_config["explanation_modifier"]}')
    
    return ' '.join(parts)
```

**DNS Validation:**
```python
def validate_spf_dns(domain):
    """Validate SPF DNS record."""
    try:
        # Lookup TXT record for domain
        answers = dns.resolver.resolve(domain, 'TXT')
        
        # Find SPF record (should start with v=spf1)
        spf_record = None
        for answer in answers:
            for txt in answer.strings:
                decoded = txt.decode('utf-8')
                if decoded.startswith('v=spf1'):
                    spf_record = decoded
                    break
        
        if not spf_record:
            return {
                'is_valid': False,
                'dns_record_found': True,
                'record_value': None,
                'errors': ['No SPF record found (record does not start with v=spf1)'],
                'warnings': [],
                'mechanism_count': 0,
                'dns_lookup_count': 0,
                'over_lookup_limit': False
            }
        
        # Parse and validate record
        mechanisms = spf_record.split()
        mechanism_count = len(mechanisms)
        
        # Count DNS lookups (include, a, mx, ptr, exists)
        dns_lookup_count = sum(
            1 for m in mechanisms
            if m.lower().startswith(('include:', 'a:', 'mx:', 'ptr:', 'exists:'))
        )
        
        errors = []
        warnings = []
        
        # Check for multiple SPF records (should not have multiple TXT records with v=spf1)
        # This is already handled by returning the first one
        
        # Check all mechanism
        has_all = any(m.startswith('all') for m in mechanisms)
        if not has_all:
            warnings.append('No "all" mechanism found. SPF record should end with "-all" or "~all"')
        
        # Check lookup limit (<= 10)
        if dns_lookup_count > 10:
            errors.append(f'SPF record has {dns_lookup_count} DNS lookups, maximum is 10')
        
        return {
            'is_valid': len(errors) == 0,
            'dns_record_found': True,
            'record_value': spf_record,
            'expected_record': None,
            'errors': errors,
            'warnings': warnings,
            'mechanism_count': mechanism_count,
            'dns_lookup_count': dns_lookup_count,
            'over_lookup_limit': dns_lookup_count > 10
        }
    except dns.resolver.NoAnswer:
        return {
            'is_valid': False,
            'dns_record_found': False,
            'record_value': None,
            'errors': [f'No TXT record found for {domain}'],
            'warnings': [],
            'mechanism_count': 0,
            'dns_lookup_count': 0,
            'over_lookup_limit': False
        }
    except Exception as e:
        return {
            'is_valid': False,
            'dns_record_found': False,
            'record_value': None,
            'errors': [f'DNS lookup failed: {str(e)}'],
            'warnings': [],
            'mechanism_count': 0,
            'dns_lookup_count': 0,
            'over_lookup_limit': False
        }
```

**Email Test:**
```python
import smtplib
from email.mime.text import MIMEText

def test_email_authentication(from_address, smtp_server='localhost', smtp_port=25):
    """Test email authentication by sending a test email."""
    # Generate unique message ID
    message_id = f'<test-{uuid.uuid4()}@{from_address.split("@")[1]}>'
    
    # Create test email
    msg = MIMEText('This is a test email for authentication checking.')
    msg['Subject'] = f'[DKIM/DMARC/SPF Test] {message_id}'
    msg['From'] = from_address
    msg['To'] = from_address  # Send to self for testing
    msg['Message-ID'] = message_id
    msg['Date'] = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')
    msg['X-Test'] = 'dkim-dmarc-spf-check'
    
    # Send email
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.sendmail(from_address, [from_address], msg.as_string())
        
        return {
            'sent': True,
            'smtp_response': '250 OK',
            'message_id': message_id
        }
    except smtplib.SMTPResponseException as e:
        return {
            'sent': False,
            'smtp_response': str(e),
            'message_id': message_id
        }
    except Exception as e:
        return {
            'sent': False,
            'smtp_response': str(e),
            'message_id': message_id
        }
```

---

## Implementation Plan

### Phase 1: Backend Service (Week 1)
**Goal**: Create backend service for DNS record generation and validation

- [ ] **Task 1.1**: Create `DKIMService.py` with key generation and validation
- [ ] **Task 1.2**: Create `DMARCService.py` with policy generation and report parsing
- [ ] **Task 1.3**: Create `SPFService.py` with record generation and validation
- [ ] **Task 1.4**: Create `EmailAuthService.py` as main service
- [ ] **Task 1.5**: Implement DNS lookup utilities
- [ ] **Task 1.6**: Implement secure key storage
- [ ] **Task 1.7**: Write unit tests for services

**Deliverables:**
- Complete backend services
- DNS record generation and validation working
- Unit tests

### Phase 2: Database & Models (Week 1-2)
**Goal**: Create database storage for configurations

- [ ] **Task 2.1**: Create database tables for domains, DKIM, DMARC, SPF
- [ ] **Task 2.2**: Create model classes
- [ ] **Task 2.3**: Create database migration
- [ ] **Task 2.4**: Implement CRUD operations
- [ ] **Task 2.5**: Write model tests

**Deliverables:**
- Complete database schema
- Model classes
- Migration scripts
- CRUD operations

### Phase 3: API Layer (Week 2)
**Goal**: Create REST API for email authentication

- [ ] **Task 3.1**: Create `ApiEmailAuth.py` with all endpoints
- [ ] **Task 3.2**: Create schemas for request/response validation
- [ ] **Task 3.3**: Implement authentication and authorization
- [ ] **Task 3.4**: Add error handling
- [ ] **Task 3.5**: Write API tests
- [ ] **Task 3.6**: Create API documentation

**Deliverables:**
- Complete REST API
- All endpoints working
- API tests
- Documentation

### Phase 4: Frontend UI (Weeks 2-3)
**Goal**: Build admin interface

- [ ] **Task 4.1**: Create dashboard with overall status
- [ ] **Task 4.2**: Create domain list page
- [ ] **Task 4.3**: Create domain configuration pages
- [ ] **Task 4.4**: Create record validators
- [ ] **Task 4.5**: Create email test sender
- [ ] **Task 4.6**: Create report viewer for DMARC
- [ ] **Task 4.7**: Add internationalization
- [ ] **Task 4.8**: Write frontend tests

**Deliverables:**
- Complete admin UI
- All features working
- Responsive design
- Frontend tests

### Phase 5: Integration & Testing (Week 3)
**Goal**: Integration with SMTP server and final testing

- [ ] **Task 5.1**: Integrate with Stalwart SMTP configuration
- [ ] **Task 5.2**: Configure Stalwart to use DKIM keys
- [ ] **Task 5.3**: Set up DMARC report receiving
- [ ] **Task 5.4**: End-to-end testing
- [ ] **Task 5.5**: Performance testing
- [ ] **Task 5.6**: Security review
- [ ] **Task 5.7**: Documentation
- [ ] **Task 5.8**: User testing

**Deliverables:**
- Full integration with SMTP server
- Working DMARC report receiving
- Fully tested feature
- Complete documentation

---

## Testing

### Test Strategy

| Test Type | Coverage | Tools | Status |
|-----------|----------|-------|--------|
| Backend Unit Tests | 95%+ | pytest | ❌ To Do |
| DNS Validation Tests | All scenarios | pytest | ❌ To Do |
| API Integration Tests | All endpoints | pytest + httpx | ❌ To Do |
| Frontend Unit Tests | All components | Jest | ❌ To Do |
| Frontend Integration Tests | User flows | Cypress | ❌ To Do |
| End-to-End Tests | Complete workflows | Cypress | ❌ To Do |
| Security Tests | Key storage, permissions | OWASP ZAP | ❌ To Do |

### Example Tests

**DKIM Test:**
```python
# tests/test_service/test_dkim_service.py
import pytest
from app.service.DKIMService import DKIMService

class TestDKIMService:
    def test_generate_key_pair(self):
        """Test key pair generation."""
        service = DKIMService()
        
        key_pair = service.generate_key_pair(2048)
        
        assert 'private_key' in key_pair
        assert 'public_key' in key_pair
        assert len(key_pair['private_key']) > 1000  # RSA 2048 key is long
        assert len(key_pair['public_key']) > 200
        
        # Private key should start with PEM header
        assert key_pair['private_key'].startswith('-----BEGIN PRIVATE KEY-----')
    
    def test_generate_dns_record(self):
        """Test DNS record generation."""
        service = DKIMService()
        
        record = service.generate_dns_record(
            domain='example.com',
            selector='default',
            public_key='test_public_key'
        )
        
        assert record.startswith('v=DKIM1')
        assert 'k=rsa' in record
        assert 'p=test_public_key' in record
    
    def test_validate_dns_record(self):
        """Test DNS validation."""
        # This requires DNS server mocking
        pass
```

**DMARC Test:**
```python
# tests/test_service/test_dmarc_service.py
import pytest
from app.service.DMARCService import DMARCService

class TestDMARCService:
    def test_generate_record(self):
        """Test DMARC record generation."""
        service = DMARCService()
        
        config = {
            'policy': 'quarantine',
            'subdomain_policy': 'none',
            'pct': 50,
            'aspf': 'r',
            'adkim': 'r',
            'rua': ['mailto:dmarc-reports@example.com'],
            'ruff': [],
            'ri': 86400
        }
        
        record = service.generate_dns_record(config)
        
        assert record.startswith('v=DMARC1')
        assert 'p=quarantine' in record
        assert 'pct=50' in record
        assert 'rua=mailto:dmarc-reports@example.com' in record
    
    def test_parse_report(self):
        """Test DMARC report parsing."""
        service = DMARCService()
        
        # Use a sample XML report
        xml_report = """<?xml version="1.0" encoding="UTF-8" ?>
        <feedback>
            <report_metadata>
                <org_name>Example Inc.</org_name>
                <email>dmarc-reports@example.com</email>
                <extra_contact_info>http://example.com</extra_contact_info>
                <report_id>123456789</report_id>
                <date_range>
                    <begin>1609459200</begin>
                    <end>1609545599</end>
                </date_range>
            </report_metadata>
            <policy_published>
                <domain>example.com</domain>
                <adkim>r</adkim>
                <aspf>r</aspf>
                <p>quarantine</p>
                <sp>none</sp>
                <pct>100</pct>
            </policy_published>
            <record>
                <row>
                    <source_ip>192.0.2.1</source_ip>
                    <count>5</count>
                    <policy_evaluated>
                        <disposition>none</disposition>
                        <dkim>pass</dkim>
                        <spf>pass</spf>
                    </policy_evaluated>
                </row>
                <identifiers>
                    <header_from>example.com</header_from>
                </identifiers>
                <auth_results>
                    <dkim>
                        <domain>example.com</domain>
                        <selector>default</selector>
                        <result>pass</result>
                    </dkim>
                    <spf>
                        <domain>example.com</domain>
                        <scope>mfrom</scope>
                        <result>pass</result>
                    </spf>
                </auth_results>
            </record>
        </feedback>"""
        
        result = service.parse_aggregate_report(xml_report)
        
        assert result['report_metadata']['org_name'] == 'Example Inc.'
        assert result['policy_published']['domain'] == 'example.com'
        assert len(result['records']) == 1
```

---

## Configuration

### Environment Variables

```bash
# Email Authentication Settings
SOGO_EMAIL_AUTH_ENABLED=true
SOGO_EMAIL_AUTH_DKIM_ENABLED=true
SOGO_EMAIL_AUTH_DMARC_ENABLED=true
SOGO_EMAIL_AUTH_SPF_ENABLED=true

# DKIM Settings
SOGO_DKIM_DEFAULT_SELECTOR=default
SOGO_DKIM_DEFAULT_KEY_LENGTH=2048
SOGO_DKIM_KEY_STORAGE=/var/lib/sogo6/dkim/keys

# DMARC Settings
SOGO_DMARC_DEFAULT_POLICY=none
SOGO_DMARC_DEFAULT_PCT=100
SOGO_DMARC_REPORT_INTERRUPT=86400
SOGO_DMARC_REPORT_EMAIL=dmarc-reports@localhost

# SPF Settings
SOGO_SPF_DEFAULT_ALL_QUALIFIER=-all

# DNS Settings
SOGO_EMAIL_AUTH_DNS_TIMEOUT=5
SOGO_EMAIL_AUTH_DNS_RETRIES=3

# Security
SOGO_EMAIL_AUTH_KEY_STORAGE_MODE=600
```

### Stalwart Integration

```yaml
# In Stalwart mail.server.toml
[server.smtp]
# Enable DKIM signing
dkim = true

# DKIM configuration
[server.dkim]
# Path to DKIM keys
path = "/var/lib/sogo6/dkim/keys"

# Default selector
selector = "default"

# Sign all outgoing emails
sign-all = true

# DMARC configuration is handled via DNS, not in SMTP config
```

---

## Deployment

### Setup Steps

1. **Directory Setup:**
   ```bash
   # Create directories for DKIM keys
   mkdir -p /var/lib/sogo6/dkim/keys
   mkdir -p /var/lib/sogo6/dkim/configs
   chown -R sogo6:sogo6 /var/lib/sogo6/dkim
   chmod 700 /var/lib/sogo6/dkim
   chmod 700 /var/lib/sogo6/dkim/keys
   ```

2. **Database Migration:**
   ```bash
   # Create email authentication tables
   flask db migrate -m "Add email authentication tables"
   flask db upgrade
   ```

3. **API Configuration:**
   ```python
   # In app/api/v1/admin/__init__.py
   from .ApiEmailAuth import blp as email_auth_api
   from .ApiDKIM import blp as dkim_api
   from .ApiDMARC import blp as dmarc_api
   from .ApiSPF import blp as spf_api
   ```

4. **DNS Configuration:**
   ```bash
   # Add DKIM CNAME records for selector._domainkeys
   # Add DMARC TXT record for _dmarc.domain
   # Add SPF TXT record for domain
   ```

5. **Feature Rollout:**
   ```bash
   # Enable feature
   export SOGO_EMAIL_AUTH_ENABLED=true
   
   # Restart services
   docker-compose restart sogo6-server
   ```

---

## Success Criteria

- [ ] **Functional**: All email authentication protocols can be configured
- [ ] **User-Friendly**: Intuitive wizard guides users through setup
- [ ] **Reliable**: DNS records are validated before activation
- [ ] **Secure**: DKIM private keys stored securely
- [ ] **Comprehensive**: Supports all three protocols (DKIM, DMARC, SPF)
- [ ] **Integrated**: Works with Stalwart SMTP server
- [ ] **Monitoring**: DMARC reports are collected and displayed
- [ ] **Tested**: >90% test coverage
- [ ] **Documented**: Complete documentation for setup and usage

---

## References

### RFCs
- [RFC 6376 - DKIM](https://tools.ietf.org/html/rfc6376) - DomainKeys Identified Mail
- [RFC 7489 - DMARC](https://tools.ietf.org/html/rfc7489) - Domain-based Message Authentication, Reporting & Conformance
- [RFC 7208 - SPF](https://tools.ietf.org/html/rfc7208) - Sender Policy Framework
- [RFC 7298 - DMARC Update](https://tools.ietf.org/html/rfc7298)

### Tools & Libraries
- [cryptography](https://cryptography.io/) - Python cryptography library (for DKIM key generation)
- [dnspython](https://dnspython.readthedocs.io/) - DNS library for Python
- [OpenSSL](https://www.openssl.org/) - For DNSSEC validation (optional)

### Related Projects
- [OpenDMARC](https://www.trusteddomain.org/opendmarc/) - Open-source DMARC implementation
- [OpenDKIM](https://www.opendkim.org/) - Open-source DKIM implementation
- [SPF Tools](https://www.spftest.com/) - SPF validation tools

### Online Validators
- [MXToolbox](https://mxtoolbox.com/) - DNS lookup and validation
- [DNS Checker](https://dnschecker.org/) - Check DNS propagation globally
- [Google Admin Toolbox](https://toolbox.googleapps.com/apps/checkmx/) - Check MX, SPF, DKIM, DMARC

---

## Appendix

### DKIM Selector Strategy

```
┌─────────────────────┐──────────────────────────────────────────────┐
│     Selector         │              Use Case                            │
├─────────────────────┼──────────────────────────────────────────────┤
│ default             │ General purpose, most common                    │
│ sogo6               │ SOGo6-specific selector                          │
│ mail                │ For mail servers                                 │
│ {year}              │ Year-based rotation (e.g., 2025)                │
│ {year}-{month}      │ Monthly rotation (e.g., 2025-01)                 │
│ {random}            │ Random for security, harder to track             │
└─────────────────────┴──────────────────────────────────────────────┘

Recommended strategy:
1. Use 'default' for initial setup
2. Use year-based selectors (2025, 2026, etc.) for rotation
3. Keep old selectors active for a transition period
4. Remove old selectors after all emails with old signature have expired

Rotation schedule:
- DNS TTL: 3600 seconds (1 hour)
- Transition period: 1-2 weeks (to allow for slow DNS propagation)
- Old key retention: 1-3 months (to handle delayed emails)
```

### DMARC Policy Recommendations

```
┌─────────────────┬────────────────┬──────────────────────────────────┐
│   Phase          │   Policy       │          Description              │
├─────────────────┼────────────────┼──────────────────────────────────┤
│ Monitoring      │ none           │ Collect reports, no enforcement    │
│                 │                │ Duration: 2-4 weeks                │
│                 │                │ pct: 100%                           │
├─────────────────┼────────────────┼──────────────────────────────────┤
│ Test            │ quarantine     │ Send to spam/junk                  │
│                 │                │ Duration: 2-4 weeks                │
│                 │                │ pct: 10-50% (gradual)             │
├─────────────────┼────────────────┼──────────────────────────────────┤
│ Enforce         │ reject         │ Reject unauthenticated emails      │
│                 │                │ Duration: Ongoing                  │
│                 │                │ pct: 100%                           │
└─────────────────┴────────────────┴──────────────────────────────────┘

Typical rollout timeline:
- Weeks 1-4: Monitoring (policy=none)
- Weeks 5-8: Test (policy=quarantine, pct=10%)
- Weeks 9-12: Test (policy=quarantine, pct=50%)
- Weeks 13-16: Enforce (policy=quarantine, pct=100%)
- Week 17+: Enforce (policy=reject, pct=100%)

Note: Adjust timeline based on:
- Domain size and email volume
- Error rate in DMARC reports
- Confidence in SPF/DKIM configuration
```

### SPF Record Examples

```
Basic SPF Record:
  v=spf1 a mx ip4:192.0.2.0/24 -all
  - Allows: A records, MX records, IP range
  - Rejects: Everything else

With Includes (e.g., for Google Workspace):
  v=spf1 include:_spf.google.com ~all
  - Includes Google's SPF record
  - Soft-fail for others

With Multiple Providers:
  v=spf1 include:_spf.google.com include:spf.protection.outlook.com -all
  - Google Workspace + Microsoft 365

With Subdomains:
  v=spf1 a mx a:mail.example.com a:mail2.example.com -all
  - Allows specific mail servers

With IP Ranges:
  v=spf1 ip4:192.0.2.0/24 ip4:198.51.100.0/24 ip6:2001:db8::/32 -all
  - Allows specific IP ranges (IPv4 and IPv6)

With Redirect:
  v=spf1 redirect=example.net
  - Redirects to another domain's SPF record

With Explanation:
  v=spf1 a mx -all explanation="Please see http://example.com/spf"
  - Shows custom message on failure
```

### Security Best Practices

```
DKIM:
✓ Use RSA 2048 or 4096 bit keys
✓ Rotate keys periodically (every 6-12 months)
✓ Store private keys securely (600 permissions)
✓ Use different selectors per domain
✓ Backup private keys securely
✗ Don't use RSA 1024 bit keys (deprecated)
✗ Don't share private keys
✗ Don't store keys in version control

DMARC:
✓ Start with policy=none to collect reports
✓ Use rua to receive aggregate reports
✓ Monitor reports before enforcing
✓ Gradually increase pct before full enforcement
✓ Move to policy=reject once confident
✗ Don't start with policy=reject
✗ Don't ignore DMARC reports
✗ Don't set pct=0 (disables DMARC)

SPF:
✓ Include all legitimate mail servers
✓ Use -all or ~all at the end
✓ Keep within 10 DNS lookup limit
✓ Regularly review and update
✓ Test before deploying
✗ Don't use +all (allows all)
✗ Don't exceed 10 DNS lookups
✗ Don't use complicated nested includes
```

### Troubleshooting Checklist

**Emails going to spam:**
- [ ] Check SPF record exists and is valid
- [ ] Check DKIM record exists and is valid
- [ ] Check DMARC record exists and is valid
- [ ] Check alignment (SPF and DKIM domains match From domain)
- [ ] Check IP reputation
- [ ] Check domain reputation
- [ ] Check email content (spam triggers)

**DMARC reports not received:**
- [ ] Check rua address is correct
- [ ] Check rua address exists and can receive emails
- [ ] Check spam/junk folder for reports
- [ ] Check DNS propagation (use online validators)
- [ ] Check DMARC record syntax

**SPF permanent error:**
- [ ] Check SPF record syntax
- [ ] Check for syntax errors (missing spaces, typos)
- [ ] Check record starts with v=spf1
- [ ] Check for invalid mechanisms

**DKIM permanent error:**
- [ ] Check DKIM record exists for selector._domainkeys.domain
- [ ] Check DKIM record syntax
- [ ] Check key length matches (1024, 2048, 4096)
- [ ] Check record starts with v=DKIM1
- [ ] Check body hash (if using custom settings)
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2025-08-20 | Tobias Weiss | Initial specification |

---

**Document Status**: 📋 Draft / Specified  
**Author**: Tobias Weiss (@tobias-weiss-ai-xr)  
**Created**: 2025-08-20  
**Last Modified**: 2025-08-20  
**Target Implementation**: Q3-Q4 2025  
**Estimated Effort**: 2-3 weeks  
**Prerequisites**: None (can be implemented independently)
