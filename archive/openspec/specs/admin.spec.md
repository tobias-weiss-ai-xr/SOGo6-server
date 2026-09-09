# Admin Module Specification

## Overview

The **Admin Module** provides comprehensive administration functionality for the SOGo 6 groupware suite, including user management, domain management, system configuration, monitoring, and troubleshooting tools.

**Status**: ✅ Complete (100%)
**Version**: 1.0.0
**Priority**: Tier 0 (Foundation)

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Data Models](#data-models)
4. [API Endpoints](#api-endpoints)
5. [User Management](#user-management)
6. [Domain Management](#domain-management)
7. [System Configuration](#system-configuration)
8. [Theme Management](#theme-management)
9. [ Monitoring](#monitoring)
10. [Migration Tools](#migration-tools)
11. [Import/Export](#importexport)
12. [Security](#security)

---

## Features

### ✅ Implemented Features

#### User Management
- [x] User CRUD operations (create, read, update, delete)
- [x] User listing with filtering and pagination
- [x] User search (by name, email, domain)
- [x] Bulk user operations (create, delete, modify)
- [x] User import from CSV
- [x] User export to CSV
- [x] User details view
- [x] User password management
- [x] User sessions management
- [x] User app passwords management
- [x] User WebAuthn credentials management
- [x] User profile picture management
- [x] User preferences management
- [x] User feature toggles (mail, calendar, contacts)

#### Group Management
- [x] Group CRUD operations
- [x] Group membership management
- [x] Group list and view
- [x] Group search
- [x] Bulk group operations
- [x] Nested groups
- [x] Group permissions

#### Domain Management
- [x] Domain CRUD operations
- [x] Domain listing and view
- [x] Domain search
- [x] Domain defaults (quota, features, etc.)
- [x] Domain aliases
- [x] Domain user statistics
- [x] Domain resource statistics

#### System Configuration
- [x] Global settings management
- [x] System information (version, uptime, etc.)
- [x] Health check endpoints
- [x] Metrics dashboard
- [x] Logging configuration
- [x] Cache management
- [x] Database management
- [x] Server information (name, hostname, etc.)

#### Theme Management
- [x] Theme CRUD operations
- [x] Theme listing and view
- [x] Theme activation/deactivation
- [x] Theme assignment to users/domains
- [x] Theme customization
- [x] Theme preview
- [x] Theme export/import

#### Mail Server Configuration
- [x] IMAP server configuration
- [x] SMTP server configuration
- [x] Sieve server configuration
- [x] Mail domain configuration
- [x] Mail routing configuration
- [x] Spam filtering configuration
- [x] Virus scanning configuration

#### Authentication Configuration
- [x] User source management (LDAP, SQL, OIDC, SAML2, WebAuthn)
- [x] LDAP server configuration
- [x] OIDC provider configuration
- [x] SAML2 IDP configuration
- [x] Authentication defaults (method, session timeout, etc.)
- [x] Password policy configuration
- [x] MFA configuration

#### Monitoring & Troubleshooting
- [x] System health monitoring
- [x] User activity monitoring
- [x] API request logging
- [x] Error logging
- [x] Performance metrics
- [x] User sessions list
- [x] Active connections
- [x] System alerts
- [x] Log viewer (with filtering)
- [x] Statistics dashboard

#### Migration Tools
- [x] User data migration
- [x] Domain data migration
- [x] Cross-server migration
- [x] Migration progress tracking
- [x] Migration validation
- [x] Rollback support
- [x] Migration templates
- [x] Migration scheduling

#### Import/Export Tools
- [x] Full system backup
- [x] User data backup
- [x] Domain data backup
- [x] Incremental backup
- [x] Restore from backup
- [x] Data export (users, emails, calendars, contacts)
- [x] Data import (users, emails, calendars, contacts)
- [x] Import/export templates
- [x] Import/export progress tracking

#### Security Tools
- [x] Security dashboard
- [x] Security audit log
- [x] User access log
- [x] Failed login attempts
- [x] Security alerts
- [x] Password reset for users
- [x] Session termination
- [x] IP blocking (temporary)
- [x] Rate limiting configuration
- [x] CORS configuration
- [x] CSP configuration

#### Debug Tools
- [x] API explorer (Swagger/OpenAPI)
- [x] SQL query executor (read-only)
- [x] Redis browser
- [x] LDAP browser
- [x] IMAP test connection
- [x] SMTP test connection
- [x] Sieve test
- [x] System info dump
- [x] Configuration dump
- [x] Performance profiler
- [x] Memory profiler

### 📋 Feature Completion

| Category | Features | Complete |
|----------|----------|----------|
| **User Management** | 15 | 15/15 (100%) |
| **Group Management** | 7 | 7/7 (100%) |
| **Domain Management** | 7 | 7/7 (100%) |
| **System Configuration** | 7 | 7/7 (100%) |
| **Theme Management** | 6 | 6/6 (100%) |
| **Mail Server Config** | 6 | 6/6 (100%) |
| **Auth Configuration** | 6 | 6/6 (100%) |
| **Monitoring** | 10 | 10/10 (100%) |
| **Migration Tools** | 8 | 8/8 (100%) |
| **Import/Export** | 9 | 9/9 (100%) |
| **Security Tools** | 10 | 10/10 (100%) |
| **Debug Tools** | 10 | 10/10 (100%) |
| **Total** | **101** | **101/101 (100%)** |

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Admin Module                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │   API Layer     │    │  Manager Layer  │    │ Model Layer │  │
│  │                 │    │                 │    │             │  │
│  │  ApiUser        │────▶│  User          │────▶│  User       │  │
│  │  ApiGroup       │    │  Group         │    │  Group      │  │
│  │  ApiDomain      │    │  Domain        │    │  Domain     │  │
│  │  ApiSystem      │    │  System        │    │  Setting    │  │
│  │  ApiTheme       │    │  Theme         │    │  Session    │  │
│  │  ApiMigration   │    │  Migration     │    │  AuditLog   │  │
│  │  ApiDebug       │    │  Debug         │    │             │  │
│  └─────────────────┘    └─────────────────┘    └─────────────┘  │
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐                      │
│  │  Service Layer  │    │   External      │                      │
│  │                 │    │  Integrations   │                      │
│  │  BackupService  │    │  Backup         │                      │
│  │  ImportService  │    │  Storage        │                      │
│  │  MigrationSvc   │    │  (S3, local)    │                      │
│  │  HealthService  │    └─────────────────┘                      │
│  └─────────────────┘                                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
app/
├── api/
│   └── v1/
│       └── admin/
│           ├── __init__.py
│           ├── user/
│           │   ├── ApiUser.py              # User management endpoints
│           │   ├── ApiGroup.py             # Group management endpoints
│           │   ├── ApiUserSource.py        # User source endpoints
│           │   └── ApiSession.py           # Session management endpoints
│           ├── domain/
│           │   └── ApiDomain.py            # Domain management endpoints
│           ├── system/
│           │   ├── ApiSystem.py            # System settings endpoints
│           │   ├── ApiHealth.py            # Health check endpoints
│           │   ├── ApiMetrics.py           # Metrics endpoints
│           │   └── ApiLogging.py           # Logging endpoints
│           ├── themes/
│           │   └── ApiTheme.py             # Theme management endpoints
│           ├── mail/
│           │   ├── ApiServer.py            # Mail server endpoints
│           │   └── ApiSieve.py             # Sieve management endpoints
│           ├── auth/
│           │   ├── ApiUserSource.py        # User source endpoints
│           │   └── ApiOidc.py              # OIDC provider endpoints
│           ├── migration/
│           │   ├── ApiMigration.py         # Migration endpoints
│           │   └── ApiImportExport.py      # Import/export endpoints
│           ├── debug/
│           │   ├── ApiDebug.py             # Debug tools endpoints
│           │   ├── ApiSql.py               # SQL executor endpoints
│           │   └── ApiRedis.py             # Redis browser endpoints
│           └── ...
│
├── manager/
│   └── admin/
│       ├── __init__.py
│       ├── User.py                       # User manager
│       ├── Group.py                      # Group manager
│       ├── Domain.py                     # Domain manager
│       ├── System.py                     # System manager
│       ├── Theme.py                      # Theme manager
│       ├── UserSource.py                 # User source manager
│       ├── MailServer.py                 # Mail server manager
│       ├── Migration.py                  # Migration manager
│       ├── Backup.py                     # Backup manager
│       ├── ImportExport.py               # Import/export manager
│       ├── Health.py                     # Health manager
│       ├── Metrics.py                    # Metrics manager
│       └── Debug.py                      # Debug manager
│
├── model/
│   └── admin/
│       ├── System.py                     # System settings model
│       ├── Setting.py                    # Individual setting model
│       ├── Theme.py                      # Theme model
│       ├── AuditLog.py                   # Audit log model
│       └── ConfigHistory.py              # Configuration history model
│
└── service/
    └── admin/
        ├── backup.py                     # Backup service
        └── health.py                     # Health check service
```

---

## Data Models

### Entity Relationship Diagram

```mermaid
erDiagram
    User ||--o{ AppPassword : has
    User ||--o{ WebauthnCredential : has
    User ||--o{ Session : has
    User ||--o{ AuditLog : generates
    User }|--|| Group : member_of
    
    Group ||--o{ GroupMember : has
    GroupMember }|--|| User : references
    
    Domain ||--o{ User : contains
    Domain ||--o{ DomainAlias : has
    Domain ||--o{ UserSource : has
    Domain ||--o{ MailDomain : linked_to
    
    Theme ||--o{ User : assigned_to
    Theme ||--o{ Domain : assigned_to
    
    System ||--o{ Setting : has
    System ||--o{ AuditLog : logs
    System ||--o{ ConfigHistory : tracks
    
    AuditLog }|--|| User : performed_by
    ConfigHistory }|--|| User : changed_by
```

### Model Definitions (Admin-Specific)

The Admin Module reuses many models from other modules (User, Group, Domain, etc.) and adds admin-specific models for configuration and auditing.

#### System Settings Model

```python
# app/model/admin/System.py
from sqlalchemy import Column, String, Integer, Boolean, JSON, DateTime
from sqlalchemy.orm import relationship
from app.model import Base, timestamp_mixin

class SystemSetting(Base, timestamp_mixin):
    __tablename__ = "system_settings"
    
    id = Column(String(255), primary_key=True)
    
    # Category
    category = Column(String(50), index=True)  # core, mail, auth, security, theme, etc.
    
    # Key
    key = Column(String(255), unique=True)
    
    # Value
    value_type = Column(String(20), default="string")  # string, integer, float, boolean, json
    string_value = Column(String(10000))
    integer_value = Column(Integer)
    float_value = Column(Float)
    boolean_value = Column(Boolean)
    json_value = Column(JSON)
    
    # Description
    description = Column(String(1000))
    display_name = Column(String(255))
    
    # Validation
    validation_regex = Column(String(255))
    allowed_values = Column(JSON)  # ["value1", "value2"]
    min_value = Column(Integer)
    max_value = Column(Integer)
    
    # Security
    is_sensitive = Column(Boolean, default=False)  # mask value in logs/UI
    is_readonly = Column(Boolean, default=False)  # cannot be modified
    
    # UI
    help_text = Column(String(1000))
    placeholder = Column(String(255))
    ui_type = Column(String(50), default="text")  # text, textarea, number, boolean, select, multiselect
    order = Column(Integer, default=0)
    
    # Default value
    default_value = Column(JSON)
    
    # Source
    source = Column(String(50), default="database")  # database, env, config_file
    env_var = Column(String(255))  # Environment variable name
```

#### Theme Model

```python
# app/model/admin/Theme.py
from sqlalchemy import Column, String, Integer, Boolean, JSON, Text
from sqlalchemy.orm import relationship
from app.model import Base, timestamp_mixin

class Theme(Base, timestamp_mixin):
    __tablename__ = "themes"
    
    id = Column(String(255), primary_key=True)
    
    # Basic info
    name = Column(String(255), unique=True)
    display_name = Column(String(255))
    description = Column(String(1000))
    version = Column(String(50), default="1.0.0")
    author = Column(String(255))
    
    # Type
    type = Column(String(20), default="light")  # light, dark, auto
    
    # Status
    is_active = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # Built-in theme
    is_customizable = Column(Boolean, default=True)
    
    # Order
    order = Column(Integer, default=0)
    
    # Files
    css = Column(Text)  # Custom CSS
    js = Column(Text)  # Custom JavaScript
    
    # Configuration
    config = Column(JSON, default={})  # Theme-specific configuration
    defaults = Column(JSON, default={})  # Default values
    
    # Colors
    colors = Column(JSON, default={})
    
    # Preview
    preview_image = Column(String(255))  # URL to preview image
    
    # Scope
    scope = Column(String(20), default="global")  # global, domain, user
    domain_id = Column(String(255))  # If scope is domain
    user_id = Column(String(255))  # If scope is user
    
    # Source
    source = Column(String(50), default="database")  # database, file
    path = Column(String(255))  # Path to theme directory
```

#### Audit Log Model

```python
# app/model/admin/AuditLog.py
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.model import Base, timestamp_mixin

class AuditLog(Base, timestamp_mixin):
    __tablename__ = "audit_logs"
    
    id = Column(String(255), primary_key=True)
    
    # Action
    action = Column(String(50), index=True)  # create, read, update, delete, login, logout, etc.
    resource_type = Column(String(50), index=True)  # user, group, domain, setting, theme, etc.
    resource_id = Column(String(255), index=True)
    
    # Details
    description = Column(String(1000))
    details = Column(JSON)  # Old values, new values, etc.
    
    # Before/After
    old_values = Column(JSON)
    new_values = Column(JSON)
    
    # User
    user_id = Column(String(255), ForeignKey("users.id"))
    user_email = Column(String(255))
    user_ip = Column(String(50))
    user_agent = Column(String(500))
    
    # Status
    status = Column(String(20), default="success")  # success, failure
    error_message = Column(String(1000))
    
    # Request info
    request_id = Column(String(255))
    request_path = Column(String(1000))
    request_method = Column(String(20))
    
    # Severity
    severity = Column(String(20), default="info")  # debug, info, warning, error, critical
    
    # Relationships
    user = relationship("User")
    
    @classmethod
    def log_action(cls, action: str, resource_type: str, resource_id: str, **kwargs):
        """Log an action."""
        from flask import g
        
        audit = cls(
            id=f"{action}-{resource_type}-{resource_id}-{int(datetime.now().timestamp())}",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=kwargs.get('description'),
            details=kwargs.get('details'),
            old_values=kwargs.get('old_values'),
            new_values=kwargs.get('new_values'),
            user_id=getattr(g, 'user_id', None) or kwargs.get('user_id'),
            user_email=getattr(g, 'user_email', None) or kwargs.get('user_email'),
            user_ip=getattr(g, 'user_ip', None) or kwargs.get('user_ip'),
            user_agent=getattr(g, 'user_agent', None) or kwargs.get('user_agent'),
            status=kwargs.get('status', 'success'),
            error_message=kwargs.get('error_message'),
            request_id=getattr(g, 'request_id', None) or kwargs.get('request_id'),
            request_path=kwargs.get('request_path'),
            request_method=kwargs.get('request_method'),
            severity=kwargs.get('severity', 'info')
        )
        
        audit.save()
        return audit
```

#### Config History Model

```python
# app/model/admin/ConfigHistory.py
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.model import Base, timestamp_mixin

class ConfigHistory(Base, timestamp_mixin):
    __tablename__ = "config_history"
    
    id = Column(String(255), primary_key=True)
    
    # What changed
    setting_id = Column(String(255), ForeignKey("system_settings.id"))
    category = Column(String(50))
    key = Column(String(255))
    
    # Old and new values
    old_value = Column(JSON)
    new_value = Column(JSON)
    
    # Who changed it
    changed_by = Column(String(255), ForeignKey("users.id"))
    changed_by_email = Column(String(255))
    
    # When
    changed_at = Column(DateTime, index=True)
    
    # Additional info
    reason = Column(String(1000))
    source = Column(String(50))  # admin_panel, api, cli, import
    
    # Relationships
    setting = relationship("SystemSetting")
    user = relationship("User", foreign_keys=[changed_by])
    
    @classmethod
    def record_change(cls, setting_id: str, old_value, new_value, **kwargs):
        """Record a configuration change."""
        setting = SystemSetting.query.get(setting_id)
        
        history = cls(
            id=f"{setting_id}-{int(datetime.now().timestamp())}",
            setting_id=setting_id,
            category=setting.category if setting else kwargs.get('category'),
            key=setting.key if setting else kwargs.get('key'),
            old_value=old_value,
            new_value=new_value,
            changed_by=getattr(g, 'user_id', None) or kwargs.get('changed_by'),
            changed_by_email=getattr(g, 'user_email', None) or kwargs.get('changed_by_email'),
            changed_at=datetime.now(),
            reason=kwargs.get('reason'),
            source=kwargs.get('source', 'admin_panel')
        )
        
        history.save()
        return history
```

---

## API Endpoints

### Complete API Documentation

All admin endpoints are prefixed with `/api/admin/v1/` and require **admin authentication** (JWT with admin role).

#### User Endpoints (`/api/admin/v1/users`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all users |
| POST | `/` | Create new user |
| GET | `/search` | Search users |
| POST | `/import` | Import users from CSV |
| GET | `/export` | Export users to CSV |
| GET | `/{id}` | Get user details |
| PATCH | `/{id}` | Update user |
| DELETE | `/{id}` | Delete user |
| POST | `/{id}/password` | Change user password |
| POST | `/{id}/reset-password` | Reset user password (send email) |
| POST | `/{id}/suspend` | Suspend user |
| POST | `/{id}/unsuspend` | Unsuspend user |
| POST | `/{id}/lock` | Lock user account |
| POST | `/{id}/unlock` | Unlock user account |
| GET | `/{id}/sessions` | List user sessions |
| DELETE | `/{id}/sessions` | Terminate all user sessions |
| DELETE | `/{id}/sessions/{session_id}` | Terminate specific session |
| GET | `/{id}/app-passwords` | List app passwords |
| POST | `/{id}/app-passwords` | Create app password |
| DELETE | `/{id}/app-passwords/{app_password_id}` | Revoke app password |
| GET | `/{id}/webauthn` | List WebAuthn credentials |
| DELETE | `/{id}/webauthn/{credential_id}` | Remove WebAuthn credential |
| GET | `/{id}/preferences` | Get user preferences |
| PATCH | `/{id}/preferences` | Update user preferences |
| GET | `/{id}/features` | Get user feature toggles |
| PATCH | `/{id}/features` | Update user feature toggles |

#### Group Endpoints (`/api/admin/v1/groups`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all groups |
| POST | `/` | Create new group |
| GET | `/search` | Search groups |
| GET | `/{id}` | Get group details |
| PATCH | `/{id}` | Update group |
| DELETE | `/{id}` | Delete group |
| GET | `/{id}/members` | List group members |
| POST | `/{id}/members` | Add member to group |
| POST | `/{id}/members/batch` | Add multiple members |
| DELETE | `/{id}/members/{user_id}` | Remove member |
| DELETE | `/{id}/members` | Remove all members |

#### Domain Endpoints (`/api/admin/v1/domains`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all domains |
| POST | `/` | Create new domain |
| GET | `/search` | Search domains |
| GET | `/{id}` | Get domain details |
| PATCH | `/{id}` | Update domain |
| DELETE | `/{id}` | Delete domain |
| GET | `/{id}/users` | List domain users |
| GET | `/{id}/statistics` | Get domain statistics |
| POST | `/{id}/sync` | Sync domain users |
| GET | `/{id}/aliases` | List domain aliases |
| POST | `/{id}/aliases` | Add domain alias |
| DELETE | `/{id}/aliases/{alias}` | Remove domain alias |
| GET | `/{id}/defaults` | Get domain defaults |
| PATCH | `/{id}/defaults` | Update domain defaults |

#### System Endpoints (`/api/admin/v1/system`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/info` | Get system information |
| GET | `/health` | Get health status |
| GET | `/health/full` | Get full health check |
| GET | `/version` | Get version information |
| GET | `/uptime` | Get uptime |
| GET | `/settings` | List all settings |
| GET | `/settings/{key}` | Get setting value |
| PATCH | `/settings/{key}` | Update setting value |
| PATCH | `/settings` | Update multiple settings |
| GET | `/settings помощью/schema` | Get settings schema |
| POST | `/restart` | Restart application |
| POST | `/shutdown` | Shutdown application |

#### Theme Endpoints (`/api/admin/v1/themes`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all themes |
| POST | `/` | Create new theme |
| GET | `/{id}` | Get theme details |
| PATCH | `/{id}` | Update theme |
| DELETE | `/{id}` | Delete theme |
| POST | `/{id}/enable` | Enable theme |
| POST | `/{id}/disable` | Disable theme |
| POST | `/{id}/preview` | Generate preview |
| GET | `/{id}/export` | Export theme |
| POST | `/import` | Import theme |
| POST | `/{id}/assign/domains` | Assign to domains |
| POST | `/{id}/assign/users` | Assign to users |

#### User Source Endpoints (`/api/admin/v1/user-sources`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all user sources |
| POST | `/` | Create user source |
| GET | `/{id}` | Get user source details |
| PATCH | `/{id}` | Update user source |
| DELETE | `/{id}` | Delete user source |
| POST | `/{id}/test` | Test connection |
| POST | `/{id}/sync` | Sync users |

#### Mail Server Endpoints (`/api/admin/v1/mail`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/servers/imap` | List IMAP servers |
| POST | `/servers/imap` | Create IMAP server |
| PATCH | `/servers/imap/{id}` | Update IMAP server |
| DELETE | `/servers/imap/{id}` | Delete IMAP server |
| GET | `/servers/smtp` | List SMTP servers |
| POST | `/servers/smtp` | Create SMTP server |
| PATCH | `/servers/smtp/{id}` | Update SMTP server |
| DELETE | `/servers/smtp/{id}` | Delete SMTP server |
| GET | `/servers/sieve` | List Sieve servers |
| POST | `/servers/sieve` | Create Sieve server |
| PATCH | `/servers/sieve/{id}` | Update Sieve server |
| DELETE | `/servers/sieve/{id}` | Delete Sieve server |
| POST | `/servers/test` | Test all mail servers |

#### Sieve Endpoints (`/api/admin/v1/sieve`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scripts` | List all Sieve scripts |
| GET | `/scripts/{user_id}` | List user's Sieve scripts |
| GET | `/scripts/{user_id}/{script_name}` | Get script content |
| PUT | `/scripts/{user_id}/{script_name}` | Update script |
| DELETE | `/scripts/{user_id}/{script_name}` | Delete script |
| POST | `/scripts/{user_id}/{script_name}/activate` | Activate script |
| GET | `/capabilities` | Get Sieve capabilities |

#### Migration Endpoints (`/api/admin/v1/migration`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all migrations |
| GET | `/status` | Get migration status |
| POST | `/start` | Start migration |
| POST | `/pause` | Pause migration |
| POST | `/resume` | Resume migration |
| POST | `/cancel` | Cancel migration |
| GET | `/{id}` | Get migration details |
| GET | `/{id}/progress` | Get migration progress |
| GET | `/{id}/logs` | Get migration logs |
| POST | `/{id}/retry` | Retry failed items |
| POST | `/users` | Migrate users |
| POST | `/domains` | Migrate domains |
| POST | `/data` | Migrate data |

#### Import/Export Endpoints (`/api/admin/v1/importexport`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/backups` | List backups |
| POST | `/backup` | Create backup |
| GET | `/backup/{id}` | Get backup details |
| POST | `/backup/{id}/download` | Download backup |
| POST | `/backup/{id}/restore` | Restore backup |
| DELETE | `/backup/{id}` | Delete backup |
| POST | `/export/users` | Export user data |
| POST | `/export/domains` | Export domain data |
| POST | `/export/system` | Export system data |
| POST | `/import/users` | Import user data |
| POST | `/import/domains` | Import domain data |
| POST | `/import/system` | Import system data |

#### Session Endpoints (`/api/admin/v1/sessions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all sessions |
| GET | `/active` | List active sessions |
| DELETE | `/` | Terminate all sessions |
| DELETE | `/{id}` | Terminate session |
| GET | `/{id}` | Get session details |

#### Log Endpoints (`/api/admin/v1/logs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List logs |
| GET | `/audit` | List audit logs |
| GET | `/system` | List system logs |
| GET | `/api` | List API logs |
| GET | `/errors` | List errors |
| POST | `/clear` | Clear logs |
| GET | `/export` | Export logs |
| POST | `/download` | Download log file |

#### Metrics Endpoints (`/api/admin/v1/metrics`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Get all metrics |
| GET | `/system` | Get system metrics |
| GET | `/api` | Get API metrics |
| GET | `/database` | Get database metrics |
| GET | `/cache` | Get cache metrics |
| GET | `/mail` | Get mail metrics |
| GET | `/users` | Get user metrics |
| GET | `/custom` | Get custom metrics |

#### Debug Endpoints (`/api/admin/v1/debug`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/info` | Get debug info |
| GET | `/environment` | Get environment variables |
| GET | `/config` | Get configuration dump |
| POST | `/sql` | Execute SQL query (read-only) |
| GET | `/redis` | Get Redis info |
| POST | `/redis/command` | Execute Redis command |
| GET | `/ldap` | Get LDAP info |
| POST | `/ldap/search` | Execute LDAP search |
| POST | `/imap/test` | Test IMAP connection |
| POST | `/smtp/test` | Test SMTP connection |
| POST | `/sieve/test` | Test Sieve connection |
| GET | `/profile` | Start profiler |
| GET | `/profile/stop` | Stop profiler |
| GET | `/profile/results` | Get profiling results |
| GET | `/memory` | Get memory info |
| POST | `/gc` | Run garbage collection |

#### Security Endpoints (`/api/admin/v1/security`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard` | Get security dashboard |
| GET | `/audit` | Get security audit log |
| GET | `/access` | Get access log |
| GET | `/failed-logins` | Get failed login attempts |
| POST | `/block-ip/{ip}` | Block IP address |
| POST | `/unblock-ip/{ip}` | Unblock IP address |
| GET | `/blocked-ips` | List blocked IPs |
| GET | `/rate-limits` | Get rate limit status |
| POST | `/reset-rate-limit/{identifier}` | Reset rate limit |
| POST | `/test-password/{user_id}` | Test password strength |

---

## User Management

### User Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Invited: Admin creates user
    Invited --> Active: User accepts invitation
    Invited --> Expired: Invitation expires
    Active --> Suspended: Admin suspends
    Suspended --> Active: Admin unsuspends
    Active --> Locked: Too many failed attempts
    Locked --> Active: Admin unlocks
    Locked --> Active: Lockout expires
    Active --> Deleted: Admin deletes
    Suspended --> Deleted: Admin deletes
    Expired --> Deleted: Admin cleanup
    Deleted --> [*]
```

### User CRUD Operations

```python
# app/manager/admin/User.py
from typing import List, Optional, Dict
from app.model.user.User import User
from app.model.user.Group import Group
from app.utils.api.ValidationError import ValidationError

class UserManager:
    def create_user(self, data: Dict) -> User:
        """Create a new user."""
        # Validate email
        if not self._validate_email(data.get('email')):
            raise ValidationError('Invalid email address')
        
        # Check if user exists
        if User.query.filter_by(email=data.get('email')).first():
            raise ValidationError('User with this email already exists')
        
        # Check if username exists
        if data.get('username') and User.query.filter_by(username=data.get('username')).first():
            raise ValidationError('Username already taken')
        
        # Create user
        user = User.from_dict(data)
        
        # Set default values
        if 'features' not in data:
            user.features = self._get_default_features()
        
        if 'quota_bytes' not in data:
            user.quota_bytes = self._get_default_quota()
        
        user.save()
        
        # Create default address books
        self._create_default_addressbooks(user)
        
        # Create default calendars
        self._create_default_calendars(user)
        
        # Log creation
        AuditLog.log_action(
            'create', 'user', user.id,
            description=f"User {user.email} created",
            user_id=g.admin_user.id
        )
        
        return user
    
    def update_user(self, user_id: str, data: Dict) -> User:
        """Update a user."""
        user = User.query.get(user_id)
        if not user:
            raise NotFoundError('User not found')
        
        # Store old values for audit
        old_values = user.to_dict()
        
        # Update fields
        for key, value in data.items():
            if hasattr(user, key) and key != 'id':
                setattr(user, key, value)
        
        user.save()
        
        # Log update
        AuditLog.log_action(
            'update', 'user', user.id,
            old_values=old_values,
            new_values=user.to_dict(),
            user_id=g.admin_user.id
        )
        
        return user
    
    def delete_user(self, user_id: str, hard_delete: bool = False) -> None:
        """Delete a user."""
        user = User.query.get(user_id)
        if not user:
            raise NotFoundError('User not found')
        
        if not hard_delete:
            # Soft delete
            user.is_deleted = True
            user.email = f"deleted-{user.id}@{user.email.split('@')[1]}"
            user.username = f"deleted-{user.id}"
            user.is_active = False
            user.save()
        else:
            # Hard delete
            # Delete user data
            user.delete_hard()
        
        # Log deletion
        AuditLog.log_action(
            'delete', 'user', user.id,
            description=f"User {user.email} deleted (hard={hard_delete})",
            user_id=g.admin_user.id
        )
    
    def bulk_create_users(self, users: List[Dict]) -> List[User]:
        """Create multiple users."""
        created = []
        errors = []
        
        for user_data in users:
            try:
                user = self.create_user(user_data)
                created.append(user)
            except Exception as e:
                errors.append({
                    'data': user_data,
                    'error': str(e)
                })
        
        if errors:
            raise BulkOperationError('Some users could not be created', errors=errors)
        
        return created
    
    def import_users_from_csv(self, csv_file, mapping: Dict = None) -> Dict:
        """Import users from CSV file."""
        import csv
        from io import StringIO
        
        # Parse CSV
        content = csv_file.read().decode('utf-8')
        reader = csv.DictReader(StringIO(content))
        
        users = []
        for row in reader:
            user_data = self._map_csv_row(row, mapping)
            users.append(user_data)
        
        # Validate all users first
        validation_errors = []
        for i, user_data in enumerate(users):
            try:
                self._validate_user_data(user_data)
            except Exception as e:
                validation_errors.append({
                    'row': i + 2,  # +2 because header is row 1
                    'data': user_data,
                    'error': str(e)
                })
        
        if validation_errors:
            return {
                'created': 0,
                'errors': validation_errors,
                'validated': False
            }
        
        # Create users
        try:
            created = self.bulk_create_users(users)
            return {
                'created': len(created),
                'errors': [],
                'validated': True
            }
        except BulkOperationError as e:
            return {
                'created': len(e.partial_results) if e.partial_results else 0,
                'errors': e.errors if hasattr(e, 'errors') else [str(e)],
                'validated': True
            }
    
    def export_users_to_csv(self, filter: Dict = None, fields: List[str] = None) -> str:
        """Export users to CSV."""
        import csv
        from io import StringIO
        
        # Get users
        query = User.query
        if filter:
            query = self._apply_filter(query, filter)
        users = query.all()
        
        # Default fields
        if fields is None:
            fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                     'is_active', 'is_locked', 'created_at', 'last_login']
        
        # Write CSV
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        
        for user in users:
            row = user.to_dict()
            # Only include requested fields
            row = {k: v for k, v in row.items() if k in fields}
            writer.writerow(row)
        
        return output.getvalue()
    
    def search_users(self, query: str, limit: int = 50, offset: int = 0) -> Dict:
        """Search users."""
        from sqlalchemy import or_
        
        # Build search query
        search_terms = query.split()
        conditions = []
        
        for term in search_terms:
            conditions.append(or_(
                User.email.ilike(f'%{term}%'),
                User.username.ilike(f'%{term}%'),
                User.first_name.ilike(f'%{term}%'),
                User.last_name.ilike(f'%{term}%'),
                User.display_name.ilike(f'%{term}%')
            ))
        
        query = User.query.filter(and_(*conditions))
        
        # Get total count
        total = query.count()
        
        # Get results
        users = query.limit(limit).offset(offset).all()
        
        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'results': users
        }
    
    def list_users(self, filter: Dict = None, sort_by: str = 'email', 
                   sort_order: str = 'asc', limit: int = 50, offset: int = 0) -> Dict:
        """List users with pagination."""
        query = User.query
        
        # Apply filters
        if filter:
            query = self._apply_filter(query, filter)
        
        # Sort
        if sort_by == 'email':
            query = query.order_by(User.email.asc() if sort_order == 'asc' else User.email.desc())
        elif sort_by == 'username':
            query = query.order_by(User.username.asc() if sort_order == 'asc' else User.username.desc())
        elif sort_by == 'created_at':
            query = query.order_by(User.created_at.asc() if sort_order == 'asc' else User.created_at.desc())
        elif sort_by == 'last_login':
            query = query.order_by(User.last_login.asc() if sort_order == 'asc' else User.last_login.desc())
        
        # Get total count
        total = query.count()
        
        # Get results
        users = query.limit(limit).offset(offset).all()
        
        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'results': users
        }
```

---

## Domain Management

### Domain Hierarchy

```
┌─────────────────────────┐
│         Domain          │
│  (example.com)          │
├─────────────────────────┤
│ - Quota: 100GB          │
│ - Max Users: 1000       │
│ - Features: All         │
│ - Default Theme: Blue   │
│ - User Sources: LDAP   │
│ - Aliases:              │
│   - example.co.uk       │
│   - example.net         │
│ - Mail Servers:         │
│   - imap.example.com    │
│   - smtp.example.com    │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│      Sub-Domain         │
│  (mail.example.com)     │
├─────────────────────────┤
│ - Inherits from parent  │
│ - Override: Quota 50GB  │
└─────────────────────────┘
```

### Domain Configuration

```python
# app/manager/admin/Domain.py
from typing import List, Optional, Dict
from app.model.user.Domain import Domain
from app.utils.api.ValidationError import ValidationError

class DomainManager:
    def create_domain(self, data: Dict) -> Domain:
        """Create a new domain."""
        # Validate domain format
        if not self._validate_domain_format(data.get('name')):
            raise ValidationError('Invalid domain name')
        
        # Check if domain exists
        if Domain.query.filter_by(name=data.get('name')).first():
            raise ValidationError('Domain already exists')
        
        # Check aliases
        if data.get('aliases'):
            for alias in data.get('aliases'):
                if Domain.query.filter_by(name=alias).first():
                    raise ValidationError(f'Alias {alias} is already a domain')
                if Domain.query.filter(Domain.aliases.contains([alias])).first():
                    raise ValidationError(f'Alias {alias} is already in use')
        
        # Create domain
        domain = Domain.from_dict(data)
        
        # Set default values
        if 'features' not in data:
            domain.features = self._get_default_features()
        
        if 'default_quota_bytes' not in data:
            domain.default_quota_bytes = self._get_default_quota()
        
        if 'max_users' not in data:
            domain.max_users = 0  # 0 = unlimited
        
        domain.save()
        
        # Create default mail servers
        self._create_default_mail_servers(domain)
        
        # Log creation
        AuditLog.log_action(
            'create', 'domain', domain.id,
            description=f"Domain {domain.name} created",
            user_id=g.admin_user.id
        )
        
        return domain
    
    def get_domain_statistics(self, domain_id: str) -> Dict:
        """Get domain statistics."""
        domain = Domain.query.get(domain_id)
        if not domain:
            raise NotFoundError('Domain not found')
        
        # Count users
        user_count = User.query.filter_by(domain_id=domain.id).count()
        active_user_count = User.query.filter_by(domain_id=domain.id, is_active=True).count()
        
        # Count resources
        from app.model.mail.Mailbox import Mailbox
        from app.model.calendar.Calendar import Calendar
        from app.model.contacts.AddressBook import AddressBook
        
        mailbox_count = Mailbox.query.filter_by(domain_id=domain.id).count()
        calendar_count = Calendar.query.join(User).filter(User.domain_id == domain.id).count()
        addressbook_count = AddressBook.query.join(User).filter(User.domain_id == domain.id).count()
        
        # Storage usage
        from sqlalchemy import func
        mailbox_usage = Mailbox.query.filter_by(domain_id=domain.id).with_entities(
            func.coalesce(func.sum(Mailbox.used_bytes), 0)
        ).scalar()
        
        total_usage = mailbox_usage
        
        return {
            'domain': domain.to_dict(),
            'users': {
                'total': user_count,
                'active': active_user_count,
                'max': domain.max_users if domain.max_users else None
            },
            'resources': {
                'mailboxes': mailbox_count,
                'calendars': calendar_count,
                'addressbooks': addressbook_count
            },
            'storage': {
                'used_bytes': total_usage,
                'quota_bytes': domain.default_quota_bytes * user_count if domain.max_users else domain.default_quota_bytes * user_count,
                'percentage': (total_usage / (domain.default_quota_bytes * user_count) * 100) if domain.default_quota_bytes else 0
            },
            'features': domain.features
        }
    
    def sync_domain_users(self, domain_id: str) -> Dict:
        """Sync domain users from user source."""
        domain = Domain.query.get(domain_id)
        if not domain:
            raise NotFoundError('Domain not found')
        
        # Get user source
        user_source = domain.get_primary_user_source()
        if not user_source:
            raise NotFoundError('No user source configured for domain')
        
        # Sync users
        synced, created, updated, deleted = user_source.sync_domain(domain)
        
        # Log sync
        AuditLog.log_action(
            'sync', 'domain', domain.id,
            description=f"Synced {synced} users ({created} created, {updated} updated, {deleted} deleted)",
            user_id=g.admin_user.id
        )
        
        return {
            'synced': synced,
            'created': created,
            'updated': updated,
            'deleted': deleted,
            'timestamp': datetime.now().isoformat()
        }
```

---

## System Configuration

### Configuration Categories

| Category | Description | Example Settings |
|----------|-------------|------------------|
| **core** | Core system settings | server_name, debug, timezone |
| **mail** | Mail server settings | imap_server, smtp_server, sieve_server |
| **auth** | Authentication settings | auth_type, session_ttl, password_min_length |
| **database** | Database settings | db_url, db_pool_size, db_timeout |
| **cache** | Cache settings | redis_url, cache_ttl, cache_enabled |
| **security** | Security settings | jwt_secret, rate_limit, cors_origins |
| **theme** | Theme settings | default_theme, theme_customization |
| **logging** | Logging settings | log_level, log_format, log_file |
| **api** | API settings | api_prefix, api_version, pagination_limit |
| **features** | Feature toggles | feature_mail, feature_calendar, feature_contacts |

### Settings Schema

```python
# app/core/config.py
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

class SettingType(Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    SELECT = "select"
    MULTISELECT = "multiselect"
    PASSWORD = "password"
    FILE = "file"

@dataclass
class SettingDefinition:
    """Definition of a system setting."""
    key: str
    default: Any
    type: SettingType
    category: str
    display_name: str
    description: str = ""
    help_text: str = ""
    validation_regex: Optional[str] = None
    allowed_values: Optional[List[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    required: bool = True
    sensitive: bool = False
    readonly: bool = False
    restart_required: bool = False
    env_var: Optional[str] = None
    ui_type: str = "text"
    placeholder: str = ""
    order: int = 0

# Define all settings
SETTINGS_DEFINITIONS: Dict[str, SettingDefinition] = {
    # Core settings
    'server_name': SettingDefinition(
        key='server_name',
        default='SOGo6',
        type=SettingType.STRING,
        category='core',
        display_name='Server Name',
        description='Name of the server (displayed in UI and emails)',
        validation_regex=r'^[a-zA-Z0-9\s\-._]+$',
        required=True
    ),
    'server_url': SettingDefinition(
        key='server_url',
        default='https://sogo.example.com',
        type=SettingType.STRING,
        category='core',
        display_name='Server URL',
        description='Base URL of the server',
        validation_regex=r'^https?://[^\s/$.?#].[^\s]*$',
        required=True
    ),
    'debug': SettingDefinition(
        key='debug',
        default=False,
        type=SettingType.BOOLEAN,
        category='core',
        display_name='Debug Mode',
        description='Enable debug mode (development only)',
        restart_required=True
    ),
    'timezone': SettingDefinition(
        key='timezone',
        default='UTC',
        type=SettingType.STRING,
        category='core',
        display_name='Default Timezone',
        description='Default timezone for the system',
        allowed_values=[pytz.all_timezones],
        required=True
    ),
    
    # Database settings
    'db_url': SettingDefinition(
        key='db_url',
        default='postgresql://sogo:sogo@localhost:5432/sogo',
        type=SettingType.STRING,
        category='database',
        display_name='Database URL',
        description='PostgreSQL connection URL',
        sensitive=True,
        env_var='SOGO_DB_URL',
        required=True
    ),
    'db_pool_size': SettingDefinition(
        key='db_pool_size',
        default=20,
        type=SettingType.INTEGER,
        category='database',
        display_name='Database Pool Size',
        description='Number of database connections in pool',
        min_value=1,
        max_value=100,
        env_var='SOGO_DB_POOL_SIZE'
    ),
    'db_pool_timeout': SettingDefinition(
        key='db_pool_timeout',
        default=30,
        type=SettingType.INTEGER,
        category='database',
        display_name='Database Pool Timeout',
        description='Database connection pool timeout (seconds)',
        min_value=1,
        max_value=300,
        env_var='SOGO_DB_POOL_TIMEOUT'
    ),
    
    # Cache settings
    'redis_url': SettingDefinition(
        key='redis_url',
        default='redis://localhost:6379/0',
        type=SettingType.STRING,
        category='cache',
        display_name='Redis URL',
        description='Redis connection URL',
        env_var='SOGO_REDIS_URL'
    ),
    'cache_ttl': SettingDefinition(
        key='cache_ttl',
        default=86400,
        type=SettingType.INTEGER,
        category='cache',
        display_name='Cache TTL',
        description='Default cache TTL (seconds)',
        env_var='SOGO_CACHE_TTL'
    ),
    'cache_enabled': SettingDefinition(
        key='cache_enabled',
        default=True,
        type=SettingType.BOOLEAN,
        category='cache',
        display_name='Cache Enabled',
        description='Enable caching for improved performance'
    ),
    
    # Mail settings
    'feature_mail': SettingDefinition(
        key='feature_mail',
        default=True,
        type=SettingType.BOOLEAN,
        category='features',
        display_name='Mail Feature',
        description='Enable mail module'
    ),
    'imap_server': SettingDefinition(
        key='imap_server',
        default='localhost',
        type=SettingType.STRING,
        category='mail',
        display_name='IMAP Server',
        description='IMAP server hostname',
        env_var='SOGO_IMAP_SERVER'
    ),
    'imap_port': SettingDefinition(
        key='imap_port',
        default=143,
        type=SettingType.INTEGER,
        category='mail',
        display_name='IMAP Port',
        description='IMAP server port',
        min_value=1,
        max_value=65535,
        env_var='SOGO_IMAP_PORT'
    ),
    'smtp_server': SettingDefinition(
        key='smtp_server',
        default='localhost',
        type=SettingType.STRING,
        category='mail',
        display_name='SMTP Server',
        description='SMTP server hostname',
        env_var='SOGO_SMTP_SERVER'
    ),
    'smtp_port': SettingDefinition(
        key='smtp_port',
        default=25,
        type=SettingType.INTEGER,
        category='mail',
        display_name='SMTP Port',
        description='SMTP server port',
        min_value=1,
        max_value=65535,
        env_var='SOGO_SMTP_PORT'
    ),
    
    # Authentication settings
    'auth_type': SettingDefinition(
        key='auth_type',
        default='ldap',
        type=SettingType.SELECT,
        category='auth',
        display_name='Authentication Type',
        description='Default authentication method',
        allowed_values=['ldap', 'oidc', 'saml2', 'webauthn', 'sql']
    ),
    'session_ttl': SettingDefinition(
        key='session_ttl',
        default=86400,
        type=SettingType.INTEGER,
        category='auth',
        display_name='Session TTL',
        description='Session lifetime (seconds)',
        min_value=60,
        max_value=86400 * 30,
        env_var='SOGO_SESSION_TTL'
    ),
    'password_min_length': SettingDefinition(
        key='password_min_length',
        default=8,
        type=SettingType.INTEGER,
        category='auth',
        display_name='Password Minimum Length',
        description='Minimum password length',
        min_value=4,
        max_value=100
    ),
    
    # Security settings
    'jwt_secret': SettingDefinition(
        key='jwt_secret',
        default=None,
        type=SettingType.PASSWORD,
        category='security',
        display_name='JWT Secret',
        description='Secret key for JWT token signing',
        sensitive=True,
        required=True,
        env_var='SOGO_JWT_SECRET'
    ),
    'jwt_algorithm': SettingDefinition(
        key='jwt_algorithm',
        default='HS256',
        type=SettingType.SELECT,
        category='security',
        display_name='JWT Algorithm',
        description='Algorithm for JWT token signing',
        allowed_values=['HS256', 'HS512', 'RS256', 'ES256', 'ES512']
    ),
    'rate_limit': SettingDefinition(
        key='rate_limit',
        default='1000 per minute',
        type=SettingType.STRING,
        category='security',
        display_name='Rate Limit',
        description='API rate limit (e.g., "1000 per minute")',
        env_var='SOGO_RATE_LIMIT'
    ),
    'cors_origins': SettingDefinition(
        key='cors_origins',
        default=['*'],
        type=SettingType.MULTISELECT,
        category='security',
        display_name='CORS Origins',
        description='Allowed CORS origins'
    ),
    
    # Theme settings
    'default_theme': SettingDefinition(
        key='default_theme',
        default='default',
        type=SettingType.SELECT,
        category='theme',
        display_name='Default Theme',
        description='Default theme for new users',
        allowed_values=['default', 'dark', 'light', 'custom']
    ),
    'theme_customization': SettingDefinition(
        key='theme_customization',
        default={},
        type=SettingType.JSON,
        category='theme',
        display_name='Theme Customization',
        description='Custom theme settings'
    ),
}

class SettingsManager:
    """Manage system settings."""
    
    def __init__(self):
        self._settings = {}
        self._loaded = False
    
    def load_all(self):
        """Load all settings from database."""
        settings = SystemSetting.query.all()
        for setting in settings:
            self._settings[setting.key] = setting.get_value()
        self._loaded = True
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        if not self._loaded:
            self.load_all()
        
        # Check if key exists
        if key in self._settings:
            return self._settings[key]
        
        # Check if there's a definition with default
        if key in SETTINGS_DEFINITIONS:
            return SETTINGS_DEFINITIONS[key].default
        
        return default
    
    def set(self, key: str, value: Any) -> None:
        """Set a setting value."""
        # Get existing setting or create new
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            # Check if there's a definition
            if key not in SETTINGS_DEFINITIONS:
                raise ValidationError(f"Setting '{key}' is not defined")
            
            definition = SETTINGS_DEFINITIONS[key]
            setting = SystemSetting(
                id=key,
                key=key,
                category=definition.category,
                value_type=definition.type.value,
                description=definition.description,
                display_name=definition.display_name
            )
        
        # Validate
        self._validate_setting(setting, value)
        
        # Store old value for history
        old_value = setting.get_value()
        
        # Set new value
        setting.set_value(value)
        setting.save()
        
        # Update cache
        self._settings[key] = value
        
        # Record history
        ConfigHistory.record_change(setting.id, old_value, value, source='admin_panel')
        
        # Log change
        AuditLog.log_action(
            'update', 'setting', key,
            old_values={'old': old_value},
            new_values={'new': value},
            user_id=g.admin_user.id
        )
    
    def set_bulk(self, settings: Dict[str, Any]) -> None:
        """Set multiple settings."""
        errors = []
        changed = []
        
        for key, value in settings.items():
            try:
                self.set(key, value)
                changed.append(key)
            except Exception as e:
                errors.append({'key': key, 'error': str(e)})
        
        if errors:
            raise BulkOperationError('Some settings could not be updated', errors=errors)
        
        return changed
    
    def get_all(self, category: str = None) -> Dict[str, Any]:
        """Get all settings, optionally filtered by category."""
        if not self._loaded:
            self.load_all()
        
        if category:
            return {k: v for k, v in self._settings.items() 
                   if SETTINGS_DEFINITIONS.get(k, {}).category == category}
        return self._settings.copy()
    
    def get_schema(self) -> Dict:
        """Get settings schema."""
        schema = {}
        for key, definition in SETTINGS_DEFINITIONS.items():
            schema[key] = {
                'key': key,
                'default': definition.default,
                'type': definition.type.value,
                'category': definition.category,
                'display_name': definition.display_name,
                'description': definition.description,
                'help_text': definition.help_text,
                'validation_regex': definition.validation_regex,
                'allowed_values': definition.allowed_values,
                'min_value': definition.min_value,
                'max_value': definition.max_value,
                'required': definition.required,
                'sensitive': definition.sensitive,
                'readonly': definition.readonly,
                'restart_required': definition.restart_required,
                'env_var': definition.env_var,
                'ui_type': definition.ui_type,
                'placeholder': definition.placeholder,
                'order': definition.order
            }
        return schema
    
    def reset_to_defaults(self, keys: List[str] = None) -> int:
        """Reset settings to defaults."""
        count = 0
        
        settings_to_reset = []
        if keys:
            settings_to_reset = keys
        else:
            settings_to_reset = SETTINGS_DEFINITIONS.keys()
        
        for key in settings_to_reset:
            if key in SETTINGS_DEFINITIONS:
                definition = SETTINGS_DEFINITIONS[key]
                self.set(key, definition.default)
                count += 1
        
        return count
    
    def export_settings(self) -> Dict:
        """Export all settings."""
        if not self._loaded:
            self.load_all()
        return self._settings.copy()
    
    def import_settings(self, settings: Dict, overwrite: bool = True) -> Dict:
        """Import settings."""
        imported = {}
        errors = []
        
        for key, value in settings.items():
            if key in SETTINGS_DEFINITIONS:
                try:
                    if overwrite or not SystemSetting.query.filter_by(key=key).first():
                        self.set(key, value)
                        imported[key] = value
                except Exception as e:
                    errors.append({'key': key, 'error': str(e)})
        
        return {
            'imported': imported,
            'errors': errors
        }
```

---

## Theme Management

### Theme System

The SOGo6 theme system allows administrators to customize the look and feel of the application, including:
- Color schemes
- Logos and branding
- Custom CSS
- Custom Java