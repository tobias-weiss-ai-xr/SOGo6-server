# CalDAV Server Specification

## Overview

This specification defines the **CalDAV Server** implementation for SOGo 6, providing bi-directional calendar synchronization for CalDAV-compatible clients (Apple Calendar, Thunderbird, Android DAVx⁵, etc.). This feature extends the existing calendar module to expose calendars via the CalDAV protocol (RFC 4791) and synchronization extensions (RFC 6578).

**Status**: 📋 Draft / Specified
**Version**: 1.0.0
**Priority**: Tier 0 (Foundation)
**Effort**: High (8-12 weeks)

---

## Table of Contents

1. [Background](#background)
2. [Goals](#goals)
3. [Features](#features)
4. [Architecture](#architecture)
5. [Protocol Compliance](#protocol-compliance)
6. [API Design](#api-design)
7. [Data Models](#data-models)
8. [Endpoints](#endpoints)
9. [Client Compatibility](#client-compatibility)
10. [Implementation Plan](#implementation-plan)

---

## Background

### Current State

The SOGo 6 project currently has:
- ✅ **Calendar Module**: Complete calendar management (events, recurrence, sharing)
- ✅ **ACL Engine**: Fine-grained permission system for calendar sharing
- ✅ **External CalDAV**: Client-side fetching of remote CalDAV calendars (read-only)
- ❌ **CalDAV Server**: No native CalDAV server implementation

### Gap Analysis

The missing piece is a **native CalDAV server** that allows external clients to:
1. Discover calendars via `.well-known/caldav`
2. Access user calendars via `/caldav/calendars/{user}/`
3. Perform CRUD operations on events
4. Synchronize changes incrementally

This would complement the existing CardDAV server implementation and provide full calendar sync capabilities.

---

## Goals

### Primary Goals

1. **RFC 4791 Compliance**: Full CalDAV protocol support
2. **RFC 6578 Compliance**: Incremental synchronization support
3. **Multi-Client Support**: Works with Apple Calendar, Thunderbird, Android, etc.
4. **Existing Integration**: Leverage existing calendar module, ACL engine, and authentication system
5. **Performance**: Efficient sync for large calendar collections

### Non-Goals

1. **CalDAV Scheduling (iTIP)**: Out of scope for initial implementation
2. **Calendar Subscriptions**: Already partially implemented via external calendar sync
3. **WebDAV File Access**: Separate feature (CardDAV handles contacts)

---

## Features

### Core Features (Must Have)

#### Protocol Level
- [ ] **RFC 4918 (WebDAV)**: Full WebDAV support (PROPFIND, PROPPATCH, MKCOL, DELETE, PUT, GET, HEAD, OPTIONS, REPORT)
- [ ] **RFC 4791 (CalDAV)**: Calendar-specific extensions
- [ ] **RFC 5545 (iCalendar)**: Event data format
- [ ] **RFC 5546 (iCalendar Timezone)**: Timezone support
- [ ] **RFC 6578 (CalDAV Sync)**: Incremental synchronization
- [ ] **RFC 3744 (WebDAV ACL)**: Access control (integrate with existing ACL engine)

#### Calendar Operations
- [ ] Calendar discovery via `.well-known/caldav`
- [ ] Principal discovery (`/caldav/principals/`)
- [ ] Calendar home set discovery
- [ ] Calendar collection listing
- [ ] Calendar CRUD (MKCALENDAR, DELETE, PROPPATCH)
- [ ] Calendar properties (name, color, description, timezone)
- [ ] Calendar sharing via ACLs

#### Event Operations
- [ ] Event CRUD (PUT, GET, DELETE, HEAD)
- [ ] Event data format: iCalendar (RFC 5545)
- [ ] Recurrence support (RRULE, EXDATE, RDATE)
- [ ] Event exceptions (single occurrence overrides)
- [ ] Event attachments (via existing attachment system)
- [ ] Event alarms/reminders (VTODO support)
- [ ] Event timezone handling
- [ ] Event transparency (busy/free)
- [ ] Event status (confirmed/tentative/cancelled)

#### Synchronization
- [ ] Sync collection support (RFC 6578)
- [ ] Sync token generation and storage
- [ ] Delta synchronization
- [ ] Range-based synchronization
- [ ] Batch property retrieval
- [ ] ETag-based change detection
- [ ] Conditional requests (If-Match, If-None-Match)

#### Security
- [ ] Authentication via existing auth system (JWT, session)
- [ ] Authorization via existing ACL engine
- [ ] Rate limiting
- [ ] Input validation (XML, iCalendar)
- [ ] SSRF protection

### Extended Features (Nice to Have)

- [ ] **RFC 6638 (CalDAV Scheduling)**: iTIP support for meeting invitations
- [ ] **Free/Busy Query**: RFC 4791 Section 7.10
- [ ] **Calendar Availability**: RFC 5546
- [ ] **Timezone Service**: RFC 6047
- [ ] **Extended MKCOL**: RFC 5689
- [ ] **Calendar Filtering**: Custom REPORT queries

---

## Architecture

### Integration Points

The CalDAV server will integrate with existing components:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CalDAV Server Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ HTTP/Flask   │  │ XML Parsing  │  │ iCalendar    │      │
│  │ Handlers     │  │ (lxml)       │  │ Parser       │      │
│  │              │  │              │  │ (icalendar)   │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Business Logic Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Sync Engine  │  │ Request      │  │ Response     │      │
│  │ (RFC 6578)   │  │ Translator   │  │ Builder      │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Existing SOGo 6 Modules                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Calendar     │  │ ACL Engine   │  │ Auth System  │      │
│  │ Module       │  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Layer                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │ Redis        │  │ OpenLDAP     │      │
│  │ (Calendars)  │  │ (Cache/Sync) │  │ (Users)      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
sogo6-server/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── caldav/                          # NEW: CalDAV API
│   │           ├── __init__.py
│   │           ├── routes.py                    # Flask routes
│   │           ├── handlers/                    # Request handlers
│   │           │   ├── principals.py
│   │           │   ├── calendars.py
│   │           │   ├── events.py
│   │           │   ├── sync.py
│   │           │   └── reports.py
│   │           ├── xml/                        # XML templates
│   │           │   ├── responses.py
│   │           │   └── builders.py
│   │           └── utils.py
│   ├── module/
│   │   └── caldav/                             # NEW: CalDAV module
│   │       ├── __init__.py
│   │       ├── ModuleCalDAV.py                # Main module
│   │       ├── sync/
│   │       │   ├── SyncEngine.py              # RFC 6578 engine
│   │       │   ├── SyncTokenManager.py
│   │       │   └── ChangeDetector.py
│   │       ├── xml/
│   │       │   ├── PropFindParser.py
│   │       │   └── PropPatchParser.py
│   │       └── icalendar/
│   │           ├── ICalParser.py
│   │           └── ICalGenerator.py
└── tests/
    └── caldav/                                  # NEW: CalDAV tests
        ├── test_principals.py
        ├── test_calendars.py
        ├── test_events.py
        └── test_sync.py
```

---

## Protocol Compliance

### RFC Support Matrix

| RFC | Title | Priority | Status |
|-----|-------|----------|--------|
| 4918 | HTTP Extensions for WebDAV | t0 | ✅ Must Implement |
| 4791 | CalDAV | t0 | ✅ Must Implement |
| 5545 | iCalendar | t0 | ✅ Must Implement |
| 5546 | iCalendar Timezone | t0 | ✅ Must Implement |
| 6578 | CalDAV: Synchronization | t0 | ✅ Must Implement |
| 3744 | WebDAV Access Control | t0 | ✅ Must Implement |
| 5397 | WebDAV Current Principal | t0 | ✅ Must Implement |
| 5689 | Extended MKCOL | t0 | ✅ Must Implement |
| 6638 | CalDAV: Scheduling Extensions | t2 | ⚠️ Nice to Have |
| 6047 | iCalendar Time Zone Service | t2 | ⚠️ Nice to Have |
| 5995 | Using POST for Adding Members | t2 | ⚠️ Nice to Have |
| 6580 | Calendar Availability | t2 | ⚠️ Nice to Have |

### HTTP Methods

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| OPTIONS | `/caldav/` | `options_root` | Root capabilities |
| OPTIONS | `/caldav/principals/` | `options_principals` | Principal capabilities |
| OPTIONS | `/caldav/calendars/{user}/` | `options_calendar_home` | Calendar home capabilities |
| OPTIONS | `/caldav/calendars/{user}/{calendar}/` | `options_calendar` | Calendar capabilities |
| OPTIONS | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `options_event` | Event capabilities |
| PROPFIND | `/caldav/principals/` | `propfind_principals` | Discover principals |
| PROPFIND | `/caldav/principals/{user}/` | `propfind_principal` | Get principal |
| PROPFIND | `/caldav/calendars/{user}/` | `propfind_calendar_home` | List calendars |
| PROPFIND | `/caldav/calendars/{user}/{calendar}/` | `propfind_calendar` | Get calendar properties |
| PROPFIND | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `propfind_event` | Get event properties |
| MKCOL | `/caldav/calendars/{user}/{calendar}/` | `mkcol_calendar` | Create calendar |
| MKCALENDAR | `/caldav/calendars/{user}/{calendar}/` | `mkcalendar` | Create calendar (preferred) |
| DELETE | `/caldav/calendars/{user}/{calendar}/` | `delete_calendar` | Delete calendar |
| DELETE | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `delete_event` | Delete event |
| PROPPATCH | `/caldav/calendars/{user}/{calendar}/` | `proppatch_calendar` | Update calendar properties |
| PUT | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `put_event` | Create/update event |
| GET | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `get_event` | Get event |
| HEAD | `/caldav/calendars/{user}/{calendar}/{event}.ics` | `head_event` | Get event metadata |
| REPORT | `/caldav/calendars/{user}/{calendar}/` | `report_calendar` | Calendar reports |
| REPORT | `/caldav/calendars/{user}/{calendar}/` | `report_sync` | Sync collection |
| REPORT | `/caldav/calendars/{user}/` | `report_free_busy` | Free/busy query |

### CalDAV Properties

**Supported on Calendar Collections:**
- `D:getetag` - Resource ETag
- `D:getlastmodified` - Last modification time
- `D:resourcetype` - Resource type
- `D:displayname` - Display name
- `C:calendar-description` - Calendar description
- `C:calendar-timezone` - Calendar timezone ID
- `C:supported-calendar-component-set` - Supported components (VEVENT, VTODO, VJOURNAL)
- `C:max-resource-size` - Maximum resource size
- `C:min-date-time` - Minimum date/time range
- `C:max-date-time` - Maximum date/time range
- `C:max-instances` - Maximum recurring instances
- `C:max-attendees-per-instance` - Maximum attendees
- `C:supported-calendar-data` - Supported calendar data types
- `D:owner` - Calendar owner
- `D:acl` - Access control list
- `D:current-user-privilege-set` - Current user privileges

**Supported on Event Resources:**
- `D:getetag` - Resource ETag
- `D:getlastmodified` - Last modification time
- `D:resourcetype` - Resource type
- `C:calendar-data` - iCalendar data
- `D:getcontenttype` - Content type (text/calendar)
- `D:getcontentlength` - Content length

---

## API Design

### Flask Blueprint

```python
# sogo6-server/app/api/v1/caldav/__init__.py
from flask import Blueprint

caldav_bp = Blueprint('caldav', __name__, url_prefix='/caldav')

# Import and register sub-blueprints
from . import (
    principals,
    calendars,
    events,
    sync,
    reports,
)

caldav_bp.register_blueprint(principals.bp)
caldav_bp.register_blueprint(calendars.bp)
caldav_bp.register_blueprint(events.bp)
caldav_bp.register_blueprint(sync.bp)
caldav_bp.register_blueprint(reports.bp)
```

### Nginx Configuration

```nginx
# Add to existing nginx config
location /caldav {
    proxy_pass http://sogo6-server:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebDAV methods
    proxy_method PROPFIND;
    proxy_method PROPPATCH;
    proxy_method MKCOL;
    proxy_method MKCALENDAR;
    proxy_method REPORT;
    
    # CalDAV-specific headers
    proxy_set_header Depth $http_depth;
    proxy_set_header Destination $http_destination;
    proxy_set_header Overwrite $http_overwrite;
    proxy_set_header If-Match $http_if_match;
    proxy_set_header If-None-Match $http_if_none_match;
    
    # Timeout for sync operations
    proxy_read_timeout 300;
    proxy_connect_timeout 60;
    
    # Handle OPTIONS requests
    limit_except OPTIONS GET POST PUT DELETE PROPFIND PROPPATCH MKCOL REPORT {
        allow all;
    }
}

# Well-known URL for CalDAV discovery
location /.well-known/caldav {
    return 301 /caldav/;
}
```

---

## Data Models

### Database Extensions

The CalDAV server will use existing calendar tables with minimal extensions:

```sql
-- CalDAV sync tokens
CREATE TABLE IF NOT EXISTS caldav_sync_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    token VARCHAR(255) NOT NULL UNIQUE,
    token_type VARCHAR(20) NOT NULL DEFAULT 'primary', -- 'primary', 'shared', 'subscription'
    last_sync TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(user_id, calendar_id, token_type)
);

-- CalDAV ETags
CREATE TABLE IF NOT EXISTS caldav_etags (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(20) NOT NULL, -- 'calendar', 'event', 'todo'
    resource_id INTEGER NOT NULL,
    etag VARCHAR(255) NOT NULL,
    last_modified TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(resource_type, resource_id)
);

-- CalDAV ACLs (extends existing sharing system)
CREATE TABLE IF NOT EXISTS caldav_acls (
    id SERIAL PRIMARY KEY,
    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    principal_uri TEXT NOT NULL,
    privilege VARCHAR(50) NOT NULL, -- 'read', 'write', 'all', 'read-free-busy'
    access_type VARCHAR(20) NOT NULL, -- 'user', 'group', 'anonymous', 'authenticated'
    granted_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(calendar_id, principal_uri, privilege)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_caldav_sync_tokens_token ON caldav_sync_tokens(token);
CREATE INDEX IF NOT EXISTS idx_caldav_sync_tokens_user_calendar ON caldav_sync_tokens(user_id, calendar_id);
CREATE INDEX IF NOT EXISTS idx_caldav_etags_resource ON caldav_etags(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_caldav_acls_calendar ON caldav_acls(calendar_id);
```

### Resource Path Mapping

| Resource Type | URL Pattern | Handler | Database Entity |
|---------------|-------------|---------|-----------------|
| Root | `/caldav/` | `caldav_root` | N/A |
| Principals | `/caldav/principals/` | `principals_list` | User list |
| User Principal | `/caldav/principals/user/{email}/` | `principal_user` | User |
| Current User Principal | `/caldav/principals/user/` | `principal_current_user` | Current user |
| Calendar Home | `/caldav/calendars/{email}/` | `calendar_home` | User's calendars |
| Calendar | `/caldav/calendars/{email}/{calendar_name}/` | `calendar_collection` | Calendar |
| Event | `/caldav/calendars/{email}/{calendar_name}/{uid}.ics` | `event_resource` | Event |

---

## Endpoints

### Discovery

#### `.well-known/caldav`

**Request:**
```http
GET /.well-known/caldav HTTP/1.1
Host: sogo6.example.com
```

**Response:**
```http
HTTP/1.1 301 Moved Permanently
Location: /caldav/
```

#### CalDAV Root (OPTIONS)

**Request:**
```http
OPTIONS /caldav/ HTTP/1.1
Host: sogo6.example.com
```

**Response:**
```http
HTTP/1.1 200 OK
DAV: 1, 2, 3, calendar-access, calendar-schedule, extended-mkcol
Allow: OPTIONS, GET, PROPFIND, REPORT
Content-Length: 0
```

### Principals

#### List Principals (PROPFIND)

**Request:**
```xml
PROPFIND /caldav/principals/ HTTP/1.1
Host: sogo6.example.com
Depth: 1
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <d:principal-URL/>
  </d:prop>
</d:propfind>
```

**Response:**
```xml
HTTP/1.1 207 Multi-Status
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/principals/user/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype>
          <d:principal/>
        </d:resourcetype>
        <d:displayname>Current User</d:displayname>
        <d:principal-URL>/caldav/principals/user/</d:principal-URL>
        <c:calendar-user-address-set>
          <d:href>mailto:user@example.com</d:href>
        </c:calendar-user-address-set>
        <c:calendar-home-set>
          <d:href>/caldav/calendars/user@example.com/</d:href>
        </c:calendar-home-set>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
```

### Calendars

#### List Calendars (PROPFIND)

**Request:**
```xml
PROPFIND /caldav/calendars/user@example.com/ HTTP/1.1
Host: sogo6.example.com
Depth: 1
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <d:getlastmodified/>
    <c:calendar-description/>
    <c:supported-calendar-component-set/>
    <c:calendar-timezone/>
  </d:prop>
</d:propfind>
```

**Response:**
```xml
HTTP/1.1 207 Multi-Status
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/calendars/user@example.com/personal/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype>
          <d:collection/>
          <c:calendar/>
        </d:resourcetype>
        <d:displayname>Personal</d:displayname>
        <d:getlastmodified>2025-01-01T12:00:00Z</d:getlastmodified>
        <c:calendar-description>Personal calendar</c:calendar-description>
        <c:supported-calendar-component-set>
          <c:comp name="VEVENT"/>
          <c:comp name="VTODO"/>
        </c:supported-calendar-component-set>
        <c:calendar-timezone>/timezones/America/New_York.ics</c:calendar-timezone>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
```

#### Create Calendar (MKCALENDAR)

**Request:**
```xml
MKCALENDAR /caldav/calendars/user@example.com/new-calendar/ HTTP/1.1
Host: sogo6.example.com
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:">
  <d:set>
    <d:prop>
      <d:displayname>New Calendar</d:displayname>
      <c:calendar-description>This is a new calendar</c:calendar-description>
      <c:calendar-timezone>/timezones/America/New_York.ics</c:calendar-timezone>
      <c:supported-calendar-component-set>
        <c:comp name="VEVENT"/>
        <c:comp name="VTODO"/>
      </c:supported-calendar-component-set>
    </d:prop>
  </d:set>
</c:mkcalendar>
```

**Response:**
```http
HTTP/1.1 201 Created
Location: /caldav/calendars/user@example.com/new-calendar/
ETag: "abc123"
```

### Events

#### Get Event (GET)

**Request:**
```http
GET /caldav/calendars/user@example.com/personal/event-123.ics HTTP/1.1
Host: sogo6.example.com
Accept: text/calendar
```

**Response:**
```http
HTTP/1.1 200 OK
Content-Type: text/calendar; charset=utf-8
ETag: "def456"
Last-Modified: 2025-01-01T12:00:00Z

BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SOGo//SOGo 6//EN
BEGIN:VEVENT
UID:event-123
SUMMARY:Meeting
DTSTART:20250115T140000Z
DTEND:20250115T150000Z
DESCRIPTION:Team meeting
END:VEVENT
END:VCALENDAR
```

#### Create/Update Event (PUT)

**Request:**
```http
PUT /caldav/calendars/user@example.com/personal/event-123.ics HTTP/1.1
Host: sogo6.example.com
Content-Type: text/calendar; charset=utf-8
If-Match: "def456"

BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SOGo//SOGo 6//EN
BEGIN:VEVENT
UID:event-123
SUMMARY:Updated Meeting
DTSTART:20250115T140000Z
DTEND:20250115T153000Z
DESCRIPTION:Team meeting - extended
END:VEVENT
END:VCALENDAR
```

**Response:**
```http
HTTP/1.1 201 Created
ETag: "ghi789"
Last-Modified: 2025-01-02T10:00:00Z
```

#### Delete Event (DELETE)

**Request:**
```http
DELETE /caldav/calendars/user@example.com/personal/event-123.ics HTTP/1.1
Host: sogo6.example.com
If-Match: "ghi789"
```

**Response:**
```http
HTTP/1.1 204 No Content
```

### Synchronization

#### Sync Collection (REPORT)

**Request (Initial Sync):**
```xml
REPORT /caldav/calendars/user@example.com/personal/ HTTP/1.1
Host: sogo6.example.com
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<c:sync-collection xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop xmlns:d="DAV:">
    <d:getetag/>
    <d:getlastmodified/>
    <c:calendar-data/>
  </d:prop>
  <c:sync-token>0</c:sync-token>
  <c:sync-level>1</c:sync-level>
  <c:limit>1000</c:limit>
</c:sync-collection>
```

**Response:**
```xml
HTTP/1.1 207 Multi-Status
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:sync-token>http://sogo6.example.com/ns/sync/personal/12345</d:sync-token>
  <d:response>
    <d:href>/caldav/calendars/user@example.com/personal/event-1.ics</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>"abc123"</d:getetag>
        <d:getlastmodified>2025-01-01T12:00:00Z</d:getlastmodified>
        <c:calendar-data>BEGIN:VCALENDAR...</c:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
```

**Request (Incremental Sync):**
```xml
REPORT /caldav/calendars/user@example.com/personal/ HTTP/1.1
Host: sogo6.example.com
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8" ?>
<c:sync-collection xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop xmlns:d="DAV:">
    <d:getetag/>
    <d:getlastmodified/>
    <c:calendar-data/>
  </d:prop>
  <c:sync-token>http://sogo6.example.com/ns/sync/personal/12345</c:sync-token>
  <c:sync-level>1</c:sync-level>
</c:sync-collection>
```

---

## Client Compatibility

### Supported Clients

| Client | Platform | CalDAV Standard | Test Status | Notes |
|--------|----------|-----------------|-------------|-------|
| Apple Calendar | macOS 14+ | RFC 4791, 6578 | ⚠️ To Test | Native support |
| Apple Calendar | iOS 17+ | RFC 4791, 6578 | ⚠️ To Test | iOS CalDAV |
| Thunderbird | Desktop | RFC 4791, 6578 | ⚠️ To Test | Lightning extension |
| Evolution | Linux | RFC 4791 | ⚠️ To Test | GNOME calendar |
| DAVx⁵ | Android | RFC 4791, 6578 | ⚠️ To Test | Open-source client |
| Calendar | Android | RFC 4791 | ⚠️ To Test | Stock Android |
| InfCloud | Web | RFC 4791, 6578 | ⚠️ To Test | Test client |

### Client Configuration Examples

**Apple Calendar (macOS):**
```
Server Address: https://sogo6.example.com
Username: user@example.com
Password: ********
```

**Thunderbird:**
```
Calendar Type: On the Network
Format: CalDAV
Location: https://sogo6.example.com/caldav/calendars/user@example.com/personal/
Username: user@example.com
Password: ********
```

**Android (DAVx⁵):**
```
Base URL: https://sogo6.example.com/caldav
Username: user@example.com
Password: ********
```

---

## Implementation Plan

### Phase 1: Foundation (Weeks 1-2)
**Goal**: Set up basic infrastructure

- [ ] Create Flask blueprint (`/caldav`)
- [ ] Implement `.well-known/caldav` endpoint
- [ ] Implement OPTIONS handler for root
- [ ] Add CalDAV XML namespace support
- [ ] Create XML parsing utilities
- [ ] Create XML response builders
- [ ] Add configuration options (base path, max sizes, timeouts)

**Deliverables:**
- Basic CalDAV endpoint responding to OPTIONS
- XML parsing/generation utilities
- Configuration system

### Phase 2: Principals (Weeks 3-4)
**Goal**: Implement user discovery

- [ ] Implement principal discovery (`/caldav/principals/`)
- [ ] Implement user principal endpoints
- [ ] Add current user principal support
- [ ] Implement calendar home set discovery
- [ ] Add authentication integration
- [ ] Add ACL engine integration for principals

**Deliverables:**
- Working principal discovery
- User authentication
- Calendar home set navigation

### Phase 3: Calendar Collections (Weeks 5-6)
**Goal**: Implement calendar listing and management

- [ ] Implement calendar PROPFIND handler
- [ ] Implement MKCALENDAR handler
- [ ] Implement DELETE handler for calendars
- [ ] Implement PROPPATCH handler for calendar properties
- [ ] Integrate with existing calendar module
- [ ] Add calendar mapping (database → CalDAV path)
- [ ] Implement calendar ACLs

**Deliverables:**
- List calendars via CalDAV
- Create/delete calendars via CalDAV
- Update calendar properties

### Phase 4: Event Operations (Weeks 7-8)
**Goal**: Implement event CRUD

- [ ] Implement event PUT handler (create/update)
- [ ] Implement event GET handler (read)
- [ ] Implement event DELETE handler
- [ ] Implement event HEAD handler
- [ ] Implement event PROPFIND handler
- [ ] Integrate with existing event module
- [ ] Add iCalendar parsing (icalendar library)
- [ ] Add iCalendar generation
- [ ] Handle recurrence (RRULE, EXDATE, RDATE)
- [ ] Handle event exceptions
- [ ] Handle attachments
- [ ] Handle timezones

**Deliverables:**
- Full event CRUD via CalDAV
- Recurrence support
- Attachment handling

### Phase 5: Synchronization (Weeks 9-10)
**Goal**: Implement RFC 6578 sync

- [ ] Implement sync token generation
- [ ] Implement sync token storage (Redis)
- [ ] Implement change detection (ETag, Last-Modified)
- [ ] Implement sync collection REPORT
- [ ] Implement incremental sync
- [ ] Implement range-based sync
- [ ] Handle sync conflicts
- [ ] Implement ETag management

**Deliverables:**
- Working sync collection
- Incremental sync support
- Conflict handling

### Phase 6: Testing & Optimization (Weeks 11-12)
**Goal**: Production readiness

- [ ] Unit tests for all handlers
- [ ] Integration tests with real clients
- [ ] Performance testing
- [ ] Security testing
- [ ] Documentation
- [ ] Nginx configuration finalization
- [ ] Load testing

**Deliverables:**
- Tested with all target clients
- Performance meets targets
- Documentation complete

---

## Configuration

### Environment Variables

```bash
# CalDAV Server Settings
SOGO_CALDAV_ENABLED=true
SOGO_CALDAV_BASE_PATH=/caldav
SOGO_CALDAV_MAX_RESOURCE_SIZE=10485760  # 10MB
SOGO_CALDAV_MAX_INSTANCES=1000
SOGO_CALDAV_MIN_DATE_TIME=1970-01-01
SOGO_CALDAV_MAX_DATE_TIME=2038-01-19
SOGO_CALDAV_SYNC_TOKEN_EXPIRY=30  # days
SOGO_CALDAV_ETAG_EXPIRY=365  # days

# Performance Settings
SOGO_CALDAV_CACHE_ENABLED=true
SOGO_CALDAV_CACHE_TTL=3600  # seconds
SOGO_CALDAV_RATE_LIMIT=1000  # requests/hour
SOGO_CALDAV_RATE_LIMIT_BURST=100

# Security Settings
SOGO_CALDAV_SSL_REQUIRED=true
SOGO_CALDAV-auth_REQUIRED=true
```

### Feature Flags

```python
# In settings.py
CALDAV_FEATURES = {
    "sync": True,           # RFC 6578 sync
    "acl": True,            # RFC 3744 ACL
    "scheduling": False,    # RFC 6638 scheduling (future)
    "free_busy": True,      # Free/busy queries
    "timezone_service": True,  # RFC 6047
}
```

---

## Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| PROPFIND (100 calendars) | < 100ms | p95 percentile |
| PROPFIND (1000 events) | < 200ms | p95 percentile |
| Event PUT | < 50ms | p95 percentile |
| Event GET | < 30ms | p95 percentile |
| Sync Collection (100 changes) | < 200ms | p95 percentile |
| Full Calendar Sync | < 500ms | p95 percentile |
| Concurrent Connections | 1000+ | Maximum supported |
| Memory Usage | < 100MB | At idle |
| CPU Usage | < 10% | At idle |

### Caching Strategy

| Cache | Type | TTL | Purpose |
|-------|------|-----|---------|
| XML Responses | Memory | 5m | Cache PROPFIND responses |
| iCalendar Data | Memory | 5m | Cache parsed event data |
| ETags | Redis | 24h | Persistent ETags |
| Sync Tokens | Redis | 7d | Persistent sync state |
| Calendar List | Memory | 1m | Cache calendar listings |

---

## Security Considerations

### Authentication
- All CalDAV requests require authentication
- Support for existing auth methods (JWT, session, LDAP)
- No anonymous access by default (configurable)

### Authorization
- Integration with existing ACL engine
- Principal-based permissions
- Fine-grained access control (read, write, delete)
- Calendar owner has full control
- Shared calendar permissions honored

### Input Validation
- Validate all XML requests
- Validate iCalendar data
- Sanitize all inputs
- Prevent path traversal
- Validate content types
- Enforce size limits (prevent DoS)

### Rate Limiting
- Configurable rate limits per user/IP
- Burst handling
- Graceful degradation under load

### SSL/TLS
- HTTPS required by default
- TLS 1.2+ minimum
- Strong cipher suites

---

## Testing

### Test Strategy

| Test Type | Coverage | Tools |
|-----------|----------|-------|
| Unit Tests | 95%+ | pytest, pytest-mock |
| Integration Tests | All endpoints | pytest, httpx |
| Compliance Tests | RFC 4791, 6578 | python-caldav |
| Client Tests | All supported clients | Manual + automated |
| Performance Tests | All endpoints | locust, k6 |
| Security Tests | All endpoints | OWASP ZAP, bandit |

### Example Tests

**Unit Test (Python):**
```python
# test_caldav_principals.py
def test_propfind_principals(client, auth_headers):
    response = client.request(
        'PROPFIND',
        '/caldav/principals/',
        headers=auth_headers,
        data=caldav.propfind_request(depth=1)
    )
    assert response.status_code == 207
    assert 'application/xml' in response.headers['Content-Type']
    assert b'calendar-home-set' in response.content
```

**Integration Test:**
```python
# test_caldav_php_calendars.py
def test_create_calendar(client, auth_headers):
    mkcalendar_xml = caldav.mkcalendar_request(
        displayname="Test Calendar",
        description="Test description"
    )
    response = client.request(
        'MKCALENDAR',
        '/caldav/calendars/user@example.com/test/',
        headers=auth_headers,
        data=mkcalendar_xml
    )
    assert response.status_code == 201
    assert 'Location' in response.headers
```

**Client Test:**
```bash
# Test with InfCloud (web-based CalDAV client)
# 1. Navigate to https://infcloud.example.com/
# 2. Add new CalDAV calendar
# 3. Enter URL: https://sogo6.example.com/caldav
# 4. Enter credentials
# 5. Verify calendar list appears
# 6. Create test event
# 7. Verify event syncs correctly
```

---

## Deployment

### Prerequisites

- Python 3.11+
- Flask 3.0+
- lxml (XML parsing)
- icalendar (iCalendar parsing/generation)
- python-caldav (testing)
- Redis (sync tokens, caching)
- Nginx (reverse proxy, recommended)

### Quick Start

```bash
# Enable CalDAV in configuration
export SOGO_CALDAV_ENABLED=true

# Start the server
docker-compose up -d

# Test CalDAV discovery
curl -i https://sogo6.example.com/.well-known/caldav

# Test root OPTIONS
curl -i -X OPTIONS https://sogo6.example.com/caldav/

# Configure client (e.g., Thunderbird)
# Server: https://sogo6.example.com/caldav
# Username: user@example.com
# Password: ********
```

### Health Check

```bash
# Check CalDAV endpoint
curl -i -X OPTIONS https://sogo6.example.com/caldav/
# Expected: HTTP/1.1 200 OK, DAV header present

# Check principal discovery
curl -i -u user:password -X PROPFIND \
  -H "Depth: 0" \
  https://sogo6.example.com/caldav/principals/user/
# Expected: HTTP/1.1 207 Multi-Status

# Check calendar access
curl -i -u user:password -X PROPFIND \
  -H "Depth: 1" \
  https://sogo6.example.com/caldav/calendars/user@example.com/
# Expected: HTTP/1.1 207 Multi-Status with calendar list
```

### Monitoring

```yaml
# Prometheus metrics (add to existing metrics)
caldav_requests_total{method, endpoint, status}
caldav_request_duration_seconds{method, endpoint}
caldav_sync_operations_total
caldav_sync_conflicts_total
caldav_active_connections
caldav_memory_usage_bytes
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid credentials | Verify username/password |
| 403 Forbidden | Insufficient permissions | Check ACLs, verify calendar ownership |
| 404 Not Found | Calendar/event doesn't exist | Verify resource path |
| 405 Method Not Allowed | Method not supported | Use correct HTTP method |
| 409 Conflict | ETag mismatch | Get current ETag with HEAD or PROPFIND |
| 413 Payload Too Large | Request too large | Reduce request size |
| 500 Internal Server Error | Server error | Check logs, report bug |

### Debug Logging

```python
# Enable debug logging
import logging
logging.getLogger('sogo6.caldav').setLevel(logging.DEBUG)

# Log all requests
@caldav_bp.before_request
def log_request():
    logger.debug(f"CalDAV {request.method} {request.path}")
    if request.method in ['PROPFIND', 'PROPPATCH', 'REPORT']:
        logger.debug(f"Request body: {request.data[:1000]}")
```

---

## Success Criteria

- [ ] **Protocol Compliance**: Pass RFC 4791 and 6578 compliance tests
- [ ] **Client Compatibility**: Works with Apple Calendar, Thunderbird, DAVx⁵
- [ ] **Performance**: Meets all performance targets
- [ ] **Security**: Passes security review, no vulnerabilities
- [ ] **Reliability**: No data loss, handles edge cases gracefully
- [ ] **Documentation**: Complete API documentation
- [ ] **Testing**: >90% test coverage
- [ ] **Monitoring**: Health checks, metrics, logging in place

---

## References

### RFCs
- [RFC 4918 - HTTP Extensions for WebDAV](https://tools.ietf.org/html/rfc4918)
- [RFC 4791 - CalDAV](https://tools.ietf.org/html/rfc4791)
- [RFC 5545 - iCalendar](https://tools.ietf.org/html/rfc5545)
- [RFC 5546 - iCalendar Timezone](https://tools.ietf.org/html/rfc5546)
- [RFC 6578 - CalDAV: Synchronization](https://tools.ietf.org/html/rfc6578)
- [RFC 3744 - WebDAV Access Control](https://tools.ietf.org/html/rfc3744)
- [RFC 5397 - WebDAV Current Principal](https://tools.ietf.org/html/rfc5397)
- [RFC 5689 - Extended MKCOL](https://tools.ietf.org/html/rfc5689)
- [RFC 6638 - CalDAV: Scheduling Extensions](https://tools.ietf.org/html/rfc6638)

### Libraries
- [python-caldav](https://github.com/python-caldav/caldav) - CalDAV client library (for testing)
- [icalendar](https://github.com/collective/icalendar) - iCalendar parsing/generation
- [lxml](https://lxml.de/) - XML parsing/generation
- [sievelib](https://github.com/AlexisMega/sievelib) - Sieve library (already in use)

### Clients
- [InfCloud](https://inf-it.com/open-source/clients/infcloud/) - Web-based CalDAV client
- [DAVx⁵](https://www.davx5.com/) - Android CalDAV/CardDAV client
- [Thunderbird Calendar](https://www.thunderbird.net/en-US/calendar/) - Desktop CalDAV client

### Tools
- [CalDAVTester](https://github.com/caldav/CalDAVTester) - CalDAV compliance tester
- [CalDAVSnooper](https://github.com/kalvinalvin/CalDAVSnooper) - CalDAV debugging proxy

---

## Appendix

### CalDAV XML Namespaces

```xml
<!-- WebDAV -->
xmlns:d="DAV:"

<!-- CalDAV -->
xmlns:c="urn:ietf:params:xml:ns:caldav"

<!-- iCalendar -->
xmlns:i="urn:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6"

<!-- Calendar Server -->
xmlns:cs="http://calendarserver.org/ns/"

<!-- Apple -->
xmlns:me="http://me.com/_namespace/"
```

### Example Complete PROPFIND Response

```xml
<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/calendars/user@example.com/personal/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype>
          <d:collection/>
          <c:calendar/>
        </d:resourcetype>
        <d:displayname>Personal Calendar</d:displayname>
        <d:getlastmodified>2025-01-01T12:00:00Z</d:getlastmodified>
        <d:getetag>"abc123"</d:getetag>
        <d:owner>
          <d:href>/caldav/principals/user/user@example.com/</d:href>
        </d:owner>
        <c:calendar-description>My personal calendar</c:calendar-description>
        <c:calendar-timezone>/timezones/America/New_York.ics</c:calendar-timezone>
        <c:supported-calendar-component-set>
          <c:comp name="VEVENT"/>
          <c:comp name="VTODO"/>
        </c:supported-calendar-component-set>
        <c:max-resource-size>10485760</c:max-resource-size>
        <c:min-date-time>1970-01-01T00:00:00Z</c:min-date-time>
        <c:max-date-time>2038-01-19T03:14:07Z</c:max-date-time>
        <c:max-instances>1000</c:max-instances>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
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
**Target Implementation**: Q4 2025  
**Estimated Total Effort**: 8-12 weeks
