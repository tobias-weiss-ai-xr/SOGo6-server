# Team Calendars Specification

## 1. Overview

**Feature**: Team Calendars (Shared Calendars with ACLs)  
**Status**: ⚠️ Partially Implemented (ACL Engine: ✅ | UI: ❌ | API: ❌)  
**Priority**: Tier 0 (Foundation)  
**Effort**: 2-3 weeks  
**Dependencies**:
- Existing ACL system (✅ Complete)
- Calendar module (✅ Complete)
- Authentication system (✅ Complete)

Team Calendars allow multiple users to share and collaborate on a single calendar. This feature builds on SOGo 6's existing ACL (Access Control List) engine to provide comprehensive calendar sharing capabilities.

---

## 2. Goals

### Primary Goals
- Create team/shared calendars
- Define granular permissions for team members
- Invite users to team calendars
- Accept/reject team calendar invitations
- View and manage team calendar membership
- Color-code owned vs. shared calendars in UI

### Secondary Goals
- Auto-accept invitations for certain domains
- Import team members from LDAP groups
- Calendar-wide ACL templates
- Conflict resolution for shared calendars
- Calendar subscription (read-only access)
- Delegation (act on behalf of calendar owner)

---

## 3. Current State

**Existing Implementation:**
- ✅ ACL Engine (`CalendarAclEngine.py`) - Handles access control logic
- ✅ Calendar User Model (`CalendarUser.py`) - Supports shared calendar operations
- ✅ Calendar Sources (`CalendarSources.py`) - Finds shared calendar keys for users
- ✅ Share Level Enum (`CalendarShareLevel.py`) - Defines permission levels
- ❌ No dedicated API endpoints for team calendar management
- ❌ No UI for creating/managing team calendars
- ❌ No invitation system
- ❌ No team calendar discovery

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Interfaces                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────┐                              │
│  │   Calendar Settings           │                              │
│  │   - Create Team Calendar      │                              │
│  │   - Manage Team Members       │                              │
│  │   - Invite Users              │                              │
│  │   - Set Permissions           │                              │
│  │   - View Shared Calendars     │                              │
│  │   - Accept/Reject Invites     │                              │
│  └──────────────────────────────┘                              │
│                                                                 │
│  ┌──────────────────────────────┐                              │
│  │   Calendar Sidebar            │                              │
│  │   - Owned Calendars (blue)    │                              │
│  │   - Shared Calendars (green)  │                              │
│  │   - Subscribed (read-only)    │                              │
│  └──────────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend Services                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    API Layer                                  │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │ │
│  │  │TeamCal API│  │Sharing API│  │ACL API   │  │Invite API│    │ │
│  │  │(NEW)      │  │(NEW)      │  │(NEW)     │  │(NEW)     │    │ │
│  │  └──────┬────┘  └──────┬────┘  └──────┬────┘  └──────┬────┘    │ │
│  │         │              │              │              │        │ │
│  └─────────┼──────────────┼──────────────┼──────────────┼────────┘ │
│            │              │              │              │          │
│            ▼              ▼              ▼              ▼          │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Service Layer                             │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌─────────┐│ │
│  │  │ TeamCalendarSvc  │  │ SharingService   │  │ACLEngine││ │
│  │  │                  │  │                  │  │         ││ │
│  │  │ - Create/Delete  │  │ - Share/Unshare  │  │ - Check ││ │
│  │  │ - List/Manage    │  │ - List Shares    │  │ - Set   ││ │
│  │  │                  │  │ - Modify Access  │  │ - Access││ │
│  │  └──────────────────┘  └──────────────────┘  │  Level  ││ │
│  │                                            └─────────┘│ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Storage                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │  LDAP        │  │  Redis       │      │
│  │              │  │              │  │              │      │
│  │ - Calendars  │  │ - Users      │  │ - Invites    │      │
│  │ - ACLs       │  │ - Groups     │  │ - Pending    │      │
│  │ - Team Cal.  │  │              │  │ - Rate Limit │      │
│  │ - Invitations│  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Data Models

### Database Schema

```sql
-- Team Calendars (extends existing calendars)
-- Existing calendars table already supports shared calendars via owner_id
-- We add team-specific metadata

CREATE TABLE sogo6_team_calendars (
    id VARCHAR(36) PRIMARY KEY,  -- UUID
    calendar_id VARCHAR(36) NOT NULL REFERENCES sogo6_calendars(id),
    
    -- Team calendar metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#4CAF50',  -- Green for shared calendars
    
    -- Owner (creator)
    owner_id VARCHAR(255) NOT NULL,  -- User UID
    
    -- Default permissions for new members
    default_share_level VARCHAR(20) DEFAULT 'read_only',
    
    -- Auto-accept
    auto_accept_invites BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    UNIQUE(calendar_id),
    INDEX idx_team_calendars_owner (owner_id),
    INDEX idx_team_calendars_name (name)
);


-- Team Calendar Invitations
CREATE TABLE sogo6_team_calendar_invites (
    id VARCHAR(36) PRIMARY KEY,
    team_calendar_id VARCHAR(36) NOT NULL REFERENCES sogo6_team_calendars(id),
    
    -- Invitee details
    user_id VARCHAR(255) NOT NULL,  -- User UID or email
    user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('user', 'group', 'email')),
    
    -- Inviter
    invited_by VARCHAR(255) NOT NULL,  -- User UID who sent invite
    
    -- Permission level (requested vs actual)
    requested_share_level VARCHAR(20) NOT NULL,  -- read_only, read_write, admin
    actual_share_level VARCHAR(20),  -- granted level (if accepted)
    
    -- Status
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'revoked')) DEFAULT 'pending',
    
    -- Message
    message TEXT,
    
    -- Timestamps
    invited_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,  -- Optional expiration
    
    -- Constraints
    UNIQUE(team_calendar_id, user_id, user_type),
    INDEX idx_invites_team (team_calendar_id),
    INDEX idx_invites_user (user_id),
    INDEX idx_invites_status (status),
    INDEX idx_invites_invited (invited_at)
);


-- Calendar Sharing (explicit shares, not invitations)
-- Extends ACL system with user-friendly naming
CREATE TABLE sogo6_calendar_shares (
    id VARCHAR(36) PRIMARY KEY,
    calendar_id VARCHAR(36) NOT NULL REFERENCES sogo6_calendars(id),
    
    -- User/group being shared with
    grant_to VARCHAR(255) NOT NULL,  -- User UID, group DN, or email
    grant_type VARCHAR(20) NOT NULL CHECK (grant_type IN ('user', 'group', 'public')),
    
    -- Permission level
    share_level VARCHAR(20) NOT NULL CHECK (
        share_level IN ('none', 'free_busy', 'read_only', 'read_write', 'admin')
    ),
    
    -- Additional permissions
    can_invite BOOLEAN DEFAULT FALSE,
    can_share BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    granted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    granted_by VARCHAR(255) NOT NULL,  -- User UID who granted access
    
    UNIQUE(calendar_id, grant_to, grant_type),
    INDEX idx_shares_calendar (calendar_id),
    INDEX idx_shares_grant (grant_to, grant_type)
);


-- Audit log for calendar sharing operations
CREATE TABLE sogo6_calendar_sharing_audit (
    id VARCHAR(36) PRIMARY KEY,
    calendar_id VARCHAR(36),  -- Can be NULL for non-calendar operations
    team_calendar_id VARCHAR(36),  -- Can be NULL
    
    -- Actor
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,  -- create, delete, share, unshare, invite, accept, reject
    
    -- Details
    target_type VARCHAR(20),  -- user, group, calendar
    target_id VARCHAR(255),
    old_share_level VARCHAR(20),
    new_share_level VARCHAR(20),
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    INDEX idx_audit_calendar (calendar_id),
    INDEX idx_audit_user (user_id),
    INDEX idx_audit_action (action),
    INDEX idx_audit_created (created_at)
);
```

---

## 6. Share Levels

Based on existing `CalendarShareLevel.py`:

```python
class CalendarShareLevel:
    NONE = "none"           # No access
    FREE_BUSY = "free_busy" # View busy/available times only
    READ_ONLY = "read_only" # View events but not modify
    READ_WRITE = "read_write" # View, create, modify, cancel own events
    ADMIN = "admin"         # Full control including sharing management
```

---

## 7. API Design

### Team Calendar Endpoints

**Base URL**: `/api/v1/calendars/teams`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all team calendars the user has access to |
| POST | `/` | Create a new team calendar |
| GET | `/{team_id}` | Get team calendar details |
| PATCH | `/{team_id}` | Update team calendar |
| DELETE | `/{team_id}` | Delete team calendar |
| GET | `/{team_id}/members` | List team calendar members |
| POST | `/{team_id}/members` | Invite user to team calendar |
| GET | `/{team_id}/members/{user_id}` | Get member details |
| PATCH | `/{team_id}/members/{user_id}` | Update member permissions |
| DELETE | `/{team_id}/members/{user_id}` | Remove member from team |

### Sharing Endpoints

**Base URL**: `/api/v1/calendars/sharing`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all calendars shared with the user |
| GET | `/{calendar_id}` | Get sharing info for a calendar |
| POST | `/{calendar_id}/shares` | Share calendar with user/group |
| GET | `/{calendar_id}/shares` | List shares for a calendar |
| GET | `/{calendar_id}/shares/{grant_id}` | Get share details |
| PATCH | `/{calendar_id}/shares/{grant_id}` | Update share permissions |
| DELETE | `/{calendar_id}/shares/{grant_id}` | Remove share |

### Invitation Endpoints

**Base URL**: `/api/v1/calendars/invites`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all pending invitations for user |
| GET | `/{invite_id}` | Get invitation details |
| POST | `/{invite_id}/accept` | Accept invitation |
| POST | `/{invite_id}/reject` | Reject invitation |
| POST | `/{invite_id}/resend` | Resend invitation |
| DELETE | `/{invite_id}` | Cancel/revoke invitation |

### Request/Response Schemas

```python
from marshmallow import Schema, fields, validate
from enum import Enum


class ShareLevelEnum(Enum):
    NONE = "none"
    FREE_BUSY = "free_busy"
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    ADMIN = "admin"


class InviteStatusEnum(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVOKED = "revoked"


class GrantTypeEnum(Enum):
    USER = "user"
    GROUP = "group"
    PUBLIC = "public"


# Team Calendar Schemas

class TeamCalendarCreateSchema(Schema):
    """Create a new team calendar."""
    name = fields.String(required=True, metadata={"example": "Marketing Team Calendar"})
    description = fields.String(metadata={"example": "Shared calendar for marketing team"})
    color = fields.String(load_default="#4CAF50", 
                         metadata={"example": "#4CAF50", "description": "Calendar color in hex"})
    default_share_level = fields.String(
        load_default="read_only",
        validate=validate.OneOf([s.value for s in ShareLevelEnum]),
        metadata={"example": "read_only"}
    )
    auto_accept_invites = fields.Boolean(load_default=False,
                                         metadata={"description": "Auto-accept invitations for trusted domains"})


class TeamCalendarUpdateSchema(Schema):
    """Update a team calendar."""
    name = fields.String()
    description = fields.String()
    color = fields.String()
    default_share_level = fields.String(validate=validate.OneOf([s.value for s in ShareLevelEnum]))
    auto_accept_invites = fields.Boolean()


class TeamCalendarSchema(Schema):
    """Team calendar information."""
    id = fields.String()
    calendar_id = fields.String()
    name = fields.String()
    description = fields.String()
    color = fields.String()
    owner_id = fields.String()
    owner_name = fields.String()
    default_share_level = fields.String()
    auto_accept_invites = fields.Boolean()
    member_count = fields.Integer()
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')
    is_owner = fields.Boolean()  # Is current user the owner
    is_member = fields.Boolean()  # Is current user a member
    my_share_level = fields.String()  # Current user's permission level


class TeamCalendarListSchema(Schema):
    """List of team calendars."""
    team_calendars = fields.List(fields.Nested(TeamCalendarSchema))
    total_count = fields.Integer()


# Member Schemas

class TeamMemberInviteSchema(Schema):
    """Invite user to team calendar."""
    user_id = fields.String(required=True, 
                           metadata={"description": "User UID, email, or group DN",
                                   "example": "john.doe@example.org"})
    user_type = fields.String(
        load_default="user",
        validate=validate.OneOf([t.value for t in GrantTypeEnum]),
        metadata={"example": "user"}
    )
    share_level = fields.String(
        required=True,
        validate=validate.OneOf([s.value for s in ShareLevelEnum]),
        metadata={"example": "read_write"}
    )
    message = fields.String(load_default="", 
                           metadata={"example": "Please join our team calendar"})


class TeamMemberSchema(Schema):
    """Team calendar member information."""
    user_id = fields.String()
    user_type = fields.String()
    user_name = fields.String()
    user_email = fields.String()
    share_level = fields.String()
    can_invite = fields.Boolean()
    can_share = fields.Boolean()
    can_delete = fields.Boolean()
    invited_by = fields.String()
    invited_at = fields.DateTime(format='iso')
    accepted_at = fields.DateTime(format='iso', load_default=None)


class TeamMemberListSchema(Schema):
    """List of team calendar members."""
    members = fields.List(fields.Nested(TeamMemberSchema))
    total_count = fields.Integer()
    can_invite_more = fields.Boolean()  # Does current user have permission to invite


# Invitation Schemas

class CalendarInviteSchema(Schema):
    """Calendar invitation information."""
    id = fields.String()
    team_calendar_id = fields.String()
    team_calendar_name = fields.String()
    invited_by = fields.String()
    invited_by_name = fields.String()
    requested_share_level = fields.String()
    message = fields.String()
    status = fields.String()
    invited_at = fields.DateTime(format='iso')
    expires_at = fields.DateTime(format='iso', load_default=None)


class CalendarInviteListSchema(Schema):
    """List of pending invitations."""
    invitations = fields.List(fields.Nested(CalendarInviteSchema))
    total_count = fields.Integer()


class CalendarInviteResponseSchema(Schema):
    """Response to invitation action."""
    invite_id = fields.String()
    team_calendar_id = fields.String()
    action = fields.String()  # accept, reject, resend
    share_level = fields.String()  # actual granted level
    message = fields.String()


# Sharing Schemas

class CalendarShareCreateSchema(Schema):
    """Share calendar with user/group."""
    grant_to = fields.String(required=True, 
                           metadata={"description": "User UID, group DN, or 'public'",
                                   "example": "john.doe@example.org"})
    grant_type = fields.String(
        load_default="user",
        validate=validate.OneOf([t.value for t in GrantTypeEnum]),
        metadata={"example": "user"}
    )
    share_level = fields.String(
        required=True,
        validate=validate.OneOf([s.value for s in ShareLevelEnum]),
        metadata={"example": "read_write"}
    )
    can_invite = fields.Boolean(load_default=False)
    can_share = fields.Boolean(load_default=False)
    can_delete = fields.Boolean(load_default=False)


class CalendarShareSchema(Schema):
    """Calendar share information."""
    id = fields.String()
    calendar_id = fields.String()
    grant_to = fields.String()
    grant_type = fields.String()
    share_level = fields.String()
    can_invite = fields.Boolean()
    can_share = fields.Boolean()
    can_delete = fields.Boolean()
    granted_at = fields.DateTime(format='iso')
    granted_by = fields.String()


class CalendarShareListSchema(Schema):
    """List of calendar shares."""
    shares = fields.List(fields.Nested(CalendarShareSchema))
    total_count = fields.Integer()
```

---

## 8. Implementation

### Team Calendar Service

```python
# sogo6-server/app/service/TeamCalendarService.py

from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

from app.module.calendar.ModuleCalendar import ModuleCalendar
from app.module.calendar.acl.CalendarAclEngine import CalendarAclEngine
from app.model.calendar.CalendarUser import CalendarUser


class TeamCalendarService:
    """Service for managing team calendars and sharing."""
    
    def __init__(self, db, ldap_client=None):
        self.db = db
        self.ldap = ldap_client
        self.calendar_module = ModuleCalendar(db)
        self.acl_engine = CalendarAclEngine(db)
    
    def create_team_calendar(self, user_id: str, name: str, description: str = "",
                               color: str = "#4CAF50", 
                               default_share_level: str = "read_only") -> Dict:
        """Create a new team calendar."""
        # Create underlying calendar
        calendar = self.calendar_module.create_calendar(
            name=name,
            description=description,
            color=color,
            owner_id=user_id,
            is_team=True
        )
        
        # Create team calendar record
        team_cal = {
            'id': generate_uuid(),
            'calendar_id': calendar['id'],
            'name': name,
            'description': description,
            'color': color,
            'owner_id': user_id,
            'default_share_level': default_share_level,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        self.db.insert('sogo6_team_calendars', team_cal)
        
        # Grant owner full permission
        self._grant_self_access(user_id, calendar['id'], 'admin')
        
        return team_cal
    
    def invite_to_team_calendar(self, team_calendar_id: str, user_id: str,
                                 invited_by: str, share_level: str,
                                 message: str = "") -> Dict:
        """Invite a user to a team calendar."""
        # Get team calendar
        team_cal = self._get_team_calendar(team_calendar_id)
        if not team_cal:
            raise Exception(f"Team calendar {team_calendar_id} not found")
        
        # Check permissions (must be owner or have can_invite)
        self._check_permission(team_calendar_id, invited_by, 'can_invite')
        
        # Create invitation
        invite = {
            'id': generate_uuid(),
            'team_calendar_id': team_calendar_id,
            'user_id': user_id,
            'user_type': 'user',
            'invited_by': invited_by,
            'requested_share_level': share_level,
            'status': 'pending',
            'message': message,
            'invited_at': datetime.now(timezone.utc)
        }
        
        self.db.insert('sogo6_team_calendar_invites', invite)
        
        return invite
    
    def accept_invitation(self, invite_id: str, accepting_user_id: str) -> Dict:
        """Accept a team calendar invitation."""
        invite = self._get_invitation(invite_id)
        if not invite:
            raise Exception(f"Invitation {invite_id} not found")
        
        # Verify user
        if invite['user_id'] != accepting_user_id:
            raise Exception("Cannot accept invitation for another user")
        
        # Update invitation
        self.db.update('sogo6_team_calendar_invites', {
            'status': 'accepted',
            'actual_share_level': invite['requested_share_level'],
            'responded_at': datetime.now(timezone.utc)
        }, {'id': invite_id})
        
        # Grant access via ACL
        team_cal = self._get_team_calendar(invite['team_calendar_id'])
        calendar = self.calendar_module.get_calendar(team_cal['calendar_id'])
        
        self.acl_engine.set_share_level(
            calendar_id=calendar['id'],
            grant_to=accepting_user_id,
            grant_type='user',
            share_level=invite['requested_share_level']
        )
        
        return invite
    
    def get_user_team_calendars(self, user_id: str) -> List[Dict]:
        """Get all team calendars the user has access to."""
        # Get calendars where user is owner
        owned = self.db.query(
            "SELECT * FROM sogo6_team_calendars WHERE owner_id = %s",
            (user_id,)
        )
        
        # Get calendars shared with user
        shared = self.db.query("""
            SELECT tc.* FROM sogo6_team_calendars tc
            JOIN sogo6_team_calendar_invites i ON tc.id = i.team_calendar_id
            WHERE i.user_id = %s AND i.status = 'accepted'
        """, (user_id,))
        
        # Get calendars via ACL
        aclShared = self.db.query("""
            SELECT tc.* FROM sogo6_team_calendars tc
            JOIN sogo6_calendar_shares s ON tc.calendar_id = s.calendar_id
            WHERE s.grant_to = %s
        """, (user_id,))
        
        # Combine and deduplicate
        all_cals = owned + shared + aclShared
        seen = set()
        result = []
        
        for cal in all_cals:
            if cal['id'] not in seen:
                seen.add(cal['id'])
                result.append(cal)
        
        # Add permission info
        for cal in result:
            share_level = self.acl_engine.get_share_level(
                cal['calendar_id'], user_id, 'user'
            )
            cal['my_share_level'] = share_level
            cal['is_owner'] = cal['owner_id'] == user_id
        
        return result
    
    def _get_team_calendar(self, team_id: str) -> Optional[Dict]:
        """Get team calendar by ID."""
        results = self.db.query(
            "SELECT * FROM sogo6_team_calendars WHERE id = %s",
            (team_id,)
        )
        return results[0] if results else None
    
    def _get_invitation(self, invite_id: str) -> Optional[Dict]:
        """Get invitation by ID."""
        results = self.db.query(
            "SELECT * FROM sogo6_team_calendar_invites WHERE id = %s",
            (invite_id,)
        )
        return results[0] if results else None
    
    def _check_permission(self, team_id: str, user_id: str, permission: str):
        """Check if user has specific permission on team calendar."""
        team_cal = self._get_team_calendar(team_id)
        if not team_cal:
            raise Exception(f"Team calendar {team_id} not found")
        
        share_level = self.acl_engine.get_share_level(
            team_cal['calendar_id'], user_id, 'user'
        )
        
        if share_level == 'admin':
            return True  # Admins can do anything
        
        permission_map = {
            'can_invite': ['admin', 'read_write'],
            'can_share': ['admin'],
            'can_delete': ['admin']
        }
        
        return share_level in permission_map.get(permission, [])
```

---

## 9. Frontend Integration

### TypeScript Utilities

```typescript
// sogo6-ui/src/features/calendars/team-calendars/api.ts

import { http } from '@/lib/http';

// Team Calendar types
export interface TeamCalendar {
  id: string;
  calendar_id: string;
  name: string;
  description: string;
  color: string;
  owner_id: string;
  is_owner: boolean;
  is_member: boolean;
  my_share_level: ShareLevel;
  member_count: number;
  created_at: string;
}

export type ShareLevel = 'none' | 'free_busy' | 'read_only' | 'read_write' | 'admin';
export type InviteStatus = 'pending' | 'accepted' | 'rejected' | 'revoked';
export type GrantType = 'user' | 'group' | 'public';

export interface TeamMember {
  user_id: string;
  user_type: GrantType;
  user_name: string;
  share_level: ShareLevel;
  can_invite: boolean;
  can_share: boolean;
  invited_at: string;
  accepted_at?: string;
}

export interface CalendarInvite {
  id: string;
  team_calendar_id: string;
  team_calendar_name: string;
  invited_by: string;
  requested_share_level: ShareLevel;
  status: InviteStatus;
  message: string;
  invited_at: string;
}

// API Endpoints
const BASE_URL = '/api/v1/calendars';

export const teamCalendarApi = {
  // Team Calendars
  list: (): Promise<TeamCalendar[]> => 
    http.get(`${BASE_URL}/teams`),
  
  create: (data: { name: string, description?: string, color?: string }): Promise<TeamCalendar> =>
    http.post(`${BASE_URL}/teams`, data),
  
  get: (id: string): Promise<TeamCalendar> =>
    http.get(`${BASE_URL}/teams/${id}`),
  
  update: (id: string, data: Partial<TeamCalendar>): Promise<TeamCalendar> =>
    http.patch(`${BASE_URL}/teams/${id}`, data),
  
  delete: (id: string): Promise<void> =>
    http.delete(`${BASE_URL}/teams/${id}`),
  
  // Members
  listMembers: (teamId: string): Promise<TeamMember[]> =>
    http.get(`${BASE_URL}/teams/${teamId}/members`),
  
  invite: (teamId: string, data: { 
    user_id: string, 
    user_type: GrantType, 
    share_level: ShareLevel 
  }): Promise<TeamMember> =>
    http.post(`${BASE_URL}/teams/${teamId}/members`, data),
  
  updateMember: (teamId: string, userId: string, data: Partial<TeamMember>): Promise<TeamMember> =>
    http.patch(`${BASE_URL}/teams/${teamId}/members/${userId}`, data),
  
  removeMember: (teamId: string, userId: string): Promise<void> =>
    http.delete(`${BASE_URL}/teams/${teamId}/members/${userId}`),
  
  // Invitations
  listInvites: (): Promise<CalendarInvite[]> =>
    http.get(`${BASE_URL}/invites`),
  
  acceptInvite: (inviteId: string): Promise<CalendarInvite> =>
    http.post(`${BASE_URL}/invites/${inviteId}/accept`),
  
  rejectInvite: (inviteId: string): Promise<CalendarInvite> =>
    http.post(`${BASE_URL}/invites/${inviteId}/reject`),
  
  resendInvite: (inviteId: string): Promise<CalendarInvite> =>
    http.post(`${BASE_URL}/invites/${inviteId}/resend`),
  
  cancelInvite: (inviteId: string): Promise<void> =>
    http.delete(`${BASE_URL}/invites/${inviteId}`),
  
  // Sharing
  share: (calendarId: string, data: { 
    grant_to: string, 
    grant_type: GrantType, 
    share_level: ShareLevel 
  }): Promise<any> =>
    http.post(`${BASE_URL}/sharing/${calendarId}/shares`, data),
}
```

---

## 10. Implementation Plan

### Phase 1: Data Layer (Week 1)
- Create database tables (`sogo6_team_calendars`, `sogo6_team_calendar_invites`, `sogo6_calendar_shares`)
- Implement database migration
- Create model classes
- Create repository classes

### Phase 2: Service Layer (Week 2)
- Implement `TeamCalendarService.py`
- Extend `CalendarAclEngine.py` for team calendar support
- Create invitation management service
- Create sharing service
- Add audit logging

### Phase 3: API Layer (Week 3)
- Implement `ApiTeamCalendar.py` endpoints
- Implement `ApiCalendarSharing.py` endpoints
- Implement `ApiCalendarInvite.py` endpoints
- Add authentication and authorization
- Add request validation

### Phase 4: Frontend Integration (Week 3-4)
- Create Team Calendar UI components
- Integrate with calendar view
- Add color-coding for shared calendars
- Add invitation flow
- Add member management UI

### Phase 5: Testing & Polish
- Unit tests for all services
- Integration tests for API endpoints
- End-to-end tests for user flows
- Performance testing
- Documentation

---

## 11. UI Implementation

### Create Team Calendar Dialog

```tsx
// sogo6-ui/src/features/calendars/team-calendars/CreateTeamCalendarDialog.tsx

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ColorPicker } from '@/components/color-picker';
import { shareLevels } from '@/lib/calendar';

export function CreateTeamCalendarDialog({ 
  open, 
  onClose, 
  onSuccess 
}: { 
  open: boolean, 
  onClose: () => void, 
  onSuccess: (calendar: TeamCalendar) => void 
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#4CAF50');
  const [defaultLevel, setDefaultLevel] = useState<ShareLevel>('read_only');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    
    setIsCreating(true);
    setError('');
    
    try {
      const calendar = await teamCalendarApi.create({
        name,
        description,
        color,
        default_share_level: defaultLevel
      });
      onSuccess(calendar);
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to create team calendar');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create Team Calendar</DialogTitle>
        </DialogHeader>
        
        <div className="space-y-4 py-4">
          <div>
            <label className="block text-sm font-medium mb-2">Calendar Name *</label>
            <Input 
              value={name} 
              onChange={(e) => setName(e.target.value)} 
              placeholder="e.g., Marketing Team Calendar"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium mb-2">Description</label>
            <Textarea 
              value={description} 
              onChange={(e) => setDescription(e.target.value)} 
              placeholder="Optional description of this calendar"
              rows={3}
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium mb-2">Color</label>
            <ColorPicker value={color} onChange={setColor} />
          </div>
          
          <div>
            <label className="block text-sm font-medium mb-2">Default Permission</label>
            <select 
              value={defaultLevel} 
              onChange={(e) => setDefaultLevel(e.target.value as ShareLevel)}
              className="w-full p-2 border rounded"
            >
              {shareLevels.map(level => (
                <option key={level} value={level}>
                  {level.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                </option>
              ))}
            </select>
          </div>
        </div>
        
        {error && (
          <div className="text-red-500 text-sm">{error}</div>
        )}
        
        <div className="flex gap-2 justify-end">
          <Button variant="outline" onClick={onClose} disabled={isCreating}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={isCreating || !name.trim()}>
            {isCreating ? 'Creating...' : 'Create Calendar'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

### Membership Management

```tsx
// sogo6-ui/src/features/calendars/team-calendars/MemberList.tsx

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Plus, X, User, Users, Crown } from 'lucide-react';

export function MemberList({ 
  teamId, 
  canInvite 
}: { 
  teamId: string, 
  canInvite: boolean 
}) {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteLevel, setInviteLevel] = useState<ShareLevel>('read_only');
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    loadMembers();
  }, [teamId]);

  const loadMembers = async () => {
    try {
      setLoading(true);
      const data = await teamCalendarApi.listMembers(teamId);
      setMembers(data);
    } catch (err) {
      // Handle error
    } finally {
      setLoading(false);
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    
    setInviting(true);
    try {
      await teamCalendarApi.invite(teamId, {
        user_id: inviteEmail,
        user_type: 'user',
        share_level: inviteLevel
      });
      setInviteEmail('');
      await loadMembers();
    } finally {
      setInviting(false);
    }
  };

  const handleRemove = async (userId: string) => {
    try {
      await teamCalendarApi.removeMember(teamId, userId);
      await loadMembers();
    } catch (err) {
      // Handle error
    }
  };

  const handleChangeLevel = async (userId: string, level: ShareLevel) => {
    try {
      await teamCalendarApi.updateMember(teamId, userId, { share_level: level });
      await loadMembers();
    } catch (err) {
      // Handle error
    }
  };

  const getLevelIcon = (level: ShareLevel) => {
    switch (level) {
      case 'admin': return <Crown className="w-4 h-4 text-yellow-500" />;
      case 'read_write': return <User className="w-4 h-4 text-blue-500" />;
      case 'read_only': return <User className="w-4 h-4 text-green-500" />;
      case 'free_busy': return <User className="w-4 h-4 text-gray-500" />;
      default: return null;
    }
  };

  return (
    <div className="space-y-4">
      {/* Invite form */}
      {canInvite && (
        <div className="flex gap-2 items-center">
          <Input 
            type="email" 
            placeholder="user@example.org" 
            value={inviteEmail} 
            onChange={(e) => setInviteEmail(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleInvite()}
            className="flex-1"
          />
          <select 
            value={inviteLevel} 
            onChange={(e) => setInviteLevel(e.target.value as ShareLevel)}
            className="p-2 border rounded"
          >
            {shareLevels.map(level => (
              <option key={level} value={level}>
                {level.replace('_', ' ')}
              </option>
            ))}
          </select>
          <Button onClick={handleInvite} disabled={inviting || !inviteEmail}>
            <Plus className="w-4 h-4 mr-1" /> Invite
          </Button>
        </div>
      )}

      {/* Member list */}
      <div className="border rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-4 text-center text-gray-500">Loading...</div>
        ) : (
          <div className="divide-y">
            {members.map(member => (
              <div key={member.user_id} className="p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {getLevelIcon(member.share_level)}
                  <div>
                    <div className="font-medium">{member.user_name || member.user_id}</div>
                    <div className="text-xs text-gray-500">{member.share_level.replace('_', ' ')}</div>
                  </div>
                </div>
                <div className="flex gap-2 items-center">
                  {/* Level selector (if can_share) */}
                  {/* Remove button (if can_share and not self) */}
                  {member.user_id !== 'me' && canInvite && (
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      onClick={() => handleRemove(member.user_id)}
                      className="text-red-500 hover:text-red-600"
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## 12. Success Criteria

- [ ] Database tables for team calendars, invitations, and shares
- [ ] Team calendar CRUD operations via API
- [ ] Invitation system (send, accept, reject, resend)
- [ ] Permission management (owner, admin, read_write, read_only, free_busy)
- [ ] UI for creating team calendars
- [ ] UI for managing team members
- [ ] UI for accepting/rejecting invitations
- [ ] Shared calendars visible in calendar view
- [ ] Color-coded shared calendars
- [ ] Performance: <500ms for calendar operations
- [ ] Rate limiting on invitation endpoints
- [ ] Audit logging for all operations
- [ ] Comprehensive test coverage
- [ ] Documentation

---

## 13. References

### Related Specifications
- `authentication.spec.md` - User authentication
- `calendar.spec.md` - Core calendar functionality
- `admin.spec.md` - Admin operations

### Source Files
- `app/module/calendar/acl/CalendarAclEngine.py` - ACL engine
- `app/module/calendar/model/CalendarShareLevel.py` - Share levels
- `app/module/calendar/model/CalendarUser.py` - Calendar user model
- `app/module/calendar/source/CalendarSources.py` - Calendar sources

### Standards
- iCalendar RFC 5545 (for calendar data)
- CalDAV RFC 4791 (for calendar sharing)

---

## Appendix A: Share Level Matrix

```
┌─────────────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│   Permission     │  None    │ Free/Busy│Read-Only │R/W      │ Admin    │
├─────────────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ View events     │          │          │ ✅       │ ✅      │ ✅      │
│ View busy times │          │ ✅       │ ✅       │ ✅      │ ✅      │
│ Create events   │          │          │          │ ✅      │ ✅      │
│ Modify own      │          │          │          │ ✅      │ ✅      │
│ Modify all      │          │          │          │         │ ✅      │
│ Delete own      │          │          │          │ ✅      │ ✅      │
│ Delete all      │          │          │          │         │ ✅      │
│ Invite others   │          │          │          │         │ ✅      │
│ Manage shares   │          │          │          │         │ ✅      │
│ Delete calendar │          │          │          │         │ ✅      │
└─────────────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

**Document Status**: 📋 Draft / Specified  
**Author**: Tobias Weiss (@tobias-weiss-ai-xr)  
**Created**: 2025-08-20  
**Last Modified**: 2025-08-20  
**Target Implementation**: Q3-Q4 2025
