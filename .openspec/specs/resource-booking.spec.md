# Resource Booking Specification

## 1. Overview

**Feature**: Bookable Resource Management  
**Status**: ✅ Partially Implemented (Backend: ✅ | Frontend: ❌ | Full integration: ❌)  
**Priority**: Tier 0 (Foundation)  
**Effort**: 2-3 weeks  
**Dependencies**:
- Calendar module (✅ Complete)
- Database (✅ Complete)
- Authentication (✅ Complete)

Resource Booking allows users to book shared resources (meeting rooms, equipment, vehicles) and prevents double-booking through calendar conflict detection. This builds on the existing `ModuleResourceBooking.py` implementation.

---

## 2. Goals

### Primary Goals
- Manage bookable resources (CRUD)
- Search and filter resources by type/capacity/location
- Check resource availability
- Book resources via calendar events
- Prevent double-booking
- Define booking policies (open, moderated, restricted)
- Group-based access control

### Secondary Goals
- Resource search with filters
- Favorite/most-used resources
- Resource calendar view
- Booking history and analytics
- Integration with external systems (Outlook, Google Calendar)
- Recurring resource bookings
- Resource categories and tags

---

## 3. Current State

**Existing Implementation Analysis:**

### Backend (✅ Complete in `app/api/v1/admin/ApiResourceBooking.py`)
```python
# Routes:
GET    /api/v1/admin/resources              # List resources
POST   /api/v1/admin/resources              # Create resource
GET    /api/v1/admin/resources/<id>         # Get resource
PATCH  /api/v1/admin/resources/<id>         # Update resource
DELETE /api/v1/admin/resources/<id>         # Delete resource
GET    /api/v1/admin/resources/available    # List available resources
POST   /api/v1/admin/resources/<id>/availability # Check availability
```

### Module (✅ Complete in `app/module/calendar/ModuleResourceBooking.py`)
- `create()` - Create new resource
- `get_all()` - List all resources
- `get_by_id()` - Get specific resource
- `get_by_email()` - Get resource by email
- `update()` - Update resource
- `delete()` - Delete resource
- `check_availability()` - Check if resource is available
- `list_available()` - List available resources

### Database (✅ Complete)
- Table: `sogo6_resources`
- Columns: id, name, description, email, resource_type, capacity, location, features, is_active, booking_policy, allowed_groups, auto_accept, created_at, updated_at

### Missing Components
- ❌ User-facing API (non-admin)
- ❌ Resource booking via calendar events
- ❌ Frontend UI for resource management
- ❌ Frontend UI for resource booking
- ❌ Availability calendar view
- ❌ Search and filtering
- ❌ Favorite resources
- ❌ Booking history

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Interfaces                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────┐                              │
│  │   Resource Booking Flow      │                              │
│  │                              │                              │
│  │  1. User creates event       │                              │
│  │  2. Click "Add Resource"     │◀──────────────────────────┐  │
│  │  3. Search/filter resources  │                              │
│  │  4. Check availability       │                              │
│  │  5. Add resource as attendee │                              │
│  │  6. Save event               │                              │
│  └──────────────────────────────┘                              │
│                                                                 │
│  ┌──────────────────────────────┐                              │
│  │   Resource Management (Admin)│                              │
│  │   - List all resources       │                              │
│  │   - Create/edit/delete       │                              │
│  │   - Set policies             │                              │
│  │   - View availability grid   │                              │
│  └──────────────────────────────┘                              │
│                                                                 │
│  ┌──────────────────────────────┐                              │
│  │   Resource Viewer             │                              │
│  │   - All resources            │                              │
│  │   - Filter by type/location  │                              │
│  │   - calendar view of bookings │                              │
│  │   - Quick booking            │                              │
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
│  │  │User Admin│  │ Resource │  │ Calendar │  │Booking   │    │ │
│  │  │API        │  │Admin API │  │API       │  │API       │    │ │
│  │  └──────┬────┘  └──────┬────┘  └──────┬────┘  └──────┬────┘    │ │
│  │         │              │              │              │        │ │
│  └─────────┼──────────────┼──────────────┼──────────────┼────────┘ │
│            │              │              │              │          │
│            ▼              ▼              ▼              ▼          │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Service Layer                             │ │
│  │  ┌──────────────────┐  ┌──────────────────┐               │ │
│  │  │ ResourceService  │  │ CalendarService   │               │ │
│  │  │                  │  │                  │               │ │
│  │  │ - CRUD           │  │ - Event Mgmt      │               │ │
│  │  │ - Availability   │  │ - Conflict Check  │               │ │
│  │  │ - Booking        │  │ - Resource Attend │               │ │
│  │  │ - Search         │  │                  │               │ │
│  │  └──────────────────┘  └──────────────────┘               │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Storage                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │    LDAP      │  │   Calendars   │      │
│  │              │  │              │  │              │      │
│  │ - Resources  │  │ - Users      │  │ - Events     │      │
│  │ - Bookings   │  │ - Groups     │  │ - Attendees  │      │
│  │              │  │              │  │ - Conflicts  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Data Models

### Database Schema

```sql
-- Resources table (existing)
-- Already defined in ModuleResourceBooking.py as sogo6_resources

CREATE TABLE IF NOT EXISTS sogo6_resources (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    email VARCHAR(255),  -- iCalendar-style resource email
    resource_type VARCHAR(20) NOT NULL DEFAULT 'room',
    capacity INTEGER,
    location VARCHAR(255),
    features TEXT[],  -- Array of features
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    booking_policy VARCHAR(20) NOT NULL DEFAULT 'open',  -- open, moderated, restricted
    allowed_groups TEXT[],  -- Array of LDAP group DNs
    auto_accept BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    INDEX idx_resources_name (name),
    INDEX idx_resources_type (resource_type),
    INDEX idx_resources_email (email),
    INDEX idx_resources_active (is_active),
    INDEX idx_resources_location (location)
);


-- Resource bookings (links events to resources)
-- This extends the existing calendar event system
CREATE TABLE IF NOT EXISTS sogo6_resource_bookings (
    id VARCHAR(36) PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL REFERENCES sogo6_calendar_objects(id),  -- Calendar event
    resource_id VARCHAR(36) NOT NULL REFERENCES sogo6_resources(id),
    
    -- Booking details
    start_ts TIMESTAMP WITH TIME ZONE NOT NULL,
    end_ts TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'confirmed',  -- confirmed, pending, cancelled, rejected
    
    -- Organizer (who booked it)
    organizer_id VARCHAR(255) NOT NULL,  -- User UID
    
    -- For moderated resources
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,
    
    -- Purpose (optional)
    booking_purpose TEXT,
    
    CREATE_index idx_bookings_event (event_id),
    INDEX idx_bookings_resource (resource_id),
    INDEX idx_bookings_organizer (organizer_id),
    INDEX idx_bookings_start (start_ts),
    INDEX idx_bookings_end (end_ts),
    INDEX idx_bookings_status (status),
    
    -- Prevent overlapping bookings (constraint)
    CONSTRAINT no_overlap_bookings EXCLUDE USING gist (
        resource_id WITH =,
        tstzrange(start_ts, end_ts) WITH &&
    )
);


-- Resource favorites (user preferences)
CREATE TABLE IF NOT EXISTS sogo6_resource_favorites (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    resource_id VARCHAR(36) NOT NULL REFERENCES sogo6_resources(id),
    
    -- Order preference
    sort_order INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    UNIQUE(user_id, resource_id),
    INDEX idx_favorites_user (user_id),
    INDEX idx_favorites_resource (resource_id)
);


-- Resource availability overrides (manual overrides)
CREATE TABLE IF NOT EXISTS sogo6_resource_overrides (
    id VARCHAR(36) PRIMARY KEY,
    resource_id VARCHAR(36) NOT NULL REFERENCES sogo6_resources(id),
    
    -- Time range
    start_ts TIMESTAMP WITH TIME ZONE NOT NULL,
    end_ts TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Override settings
    is_available BOOLEAN NOT NULL,  -- TRUE = available even if booked, FALSE = unavailable
    reason TEXT,
    
    -- Creator
    created_by VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    INDEX idx_overrides_resource (resource_id),
    INDEX idx_overrides_range (start_ts, end_ts)
);


-- Audit log
CREATE TABLE IF NOT EXISTS sogo6_resource_audit_log (
    id VARCHAR(36) PRIMARY KEY,
    action VARCHAR(50) NOT NULL,  -- create, update, delete, book, cancel, approve
    
    -- Resource/booking info
    resource_id VARCHAR(36),
    booking_id VARCHAR(36),
    event_id VARCHAR(36),
    
    -- Actor
    user_id VARCHAR(255),
    
    -- Details
    old_data JSONB,
    new_data JSONB,
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    INDEX idx_audit_resource (resource_id),
    INDEX idx_audit_user (user_id),
    INDEX idx_audit_action (action),
    INDEX idx_audit_created (created_at)
);
```

---

## 6. API Design

### New User-Facing Endpoints

**Base URL**: `/api/v1/resources`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all active resources (with filters) |
| GET | `/{resource_id}` | Get resource details |
| GET | `/search` | Search resources with filters |
| GET | `/available` | List available resources for time range |
| GET | `/{resource_id}/availability` | Check specific resource availability |
| GET | `/{resource_id}/bookings` | List bookings for a resource |
| POST | `/favorites` | Add resource to favorites |
| DELETE | `/favorites/{resource_id}` | Remove from favorites |
| GET | `/favorites` | List user's favorite resources |

### Existing Admin Endpoints

**Base URL**: `/api/admin/v1/resources`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all resources (including inactive) |
| POST | `/` | Create new resource |
| GET | `/{resource_id}` | Get resource details |
| PATCH | `/{resource_id}` | Update resource |
| DELETE | `/{resource_id}` | Delete resource |
| GET | `/available` | List available resources for time range |
| POST | `/{resource_id}/availability` | Check specific resource availability |

### Request/Response Schemas

```python
from marshmallow import Schema, fields, validate
from enum import Enum


class ResourceTypeEnum(Enum):
    ROOM = "room"
    EQUIPMENT = "equipment"
    VEHICLE = "vehicle"
    OTHER = "other"


class BookingPolicyEnum(Enum):
    OPEN = "open"          # Anyone can book (within allowed_groups)
    MODERATED = "moderated"  # Requests require approval
    RESTRICTED = "restricted" # Only specific users can book


class BookingStatusEnum(Enum):
    CONFIRMED = "confirmed"
    PENDING = "pending"      # For moderated resources
    CANCELLED = "cancelled"
    REJECTED = "rejected"    # For moderated resources


# Resource Schemas

class ResourceFeatureSchema(Schema):
    """Resource feature information."""
    feature = fields.String(required=True)
    description = fields.String()
    icon = fields.String()


class ResourceSchema(Schema):
    """Resource information."""
    id = fields.String()
    name = fields.String(required=True)
    description = fields.String()
    email = fields.Email()
    resource_type = fields.String(required=True)
    capacity = fields.Integer()
    location = fields.String()
    features = fields.List(fields.String())
    is_active = fields.Boolean()
    booking_policy = fields.String()
    auto_accept = fields.Boolean()
    is_favorite = fields.Boolean()  # Whether current user has favorited this
    current_availability = fields.String()  # Quick status
    next_available = fields.DateTime(format='iso')  # Next available time
    created_at = fields.DateTime(format='iso')
    updated_at = fields.DateTime(format='iso')


class ResourceListQuerySchema(Schema):
    """Query parameters for listing resources."""
    resource_type = fields.String(
        load_default=None,
        validate=validate.OneOf([t.value for t in ResourceTypeEnum])
    )
    min_capacity = fields.Integer(load_default=None, validate=validate.Range(min=1))
    max_capacity = fields.Integer(load_default=None, validate=validate.Range(min=1))
    location = fields.String(load_default=None)
    search = fields.String(load_default=None)  # Search name, description, features
    feature = fields.List(fields.String(), load_default=None)  # Filter by features
    active_only = fields.Boolean(load_default=True)
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    sort_by = fields.String(load_default="name", validate=validate.OneOf(["name", "capacity", "location", "created_at"]))
    sort_order = fields.String(load_default="asc", validate=validate.OneOf(["asc", "desc"]))


class ResourceListResponseSchema(Schema):
    """List of resources."""
    resources = fields.List(fields.Nested(ResourceSchema))
    total_count = fields.Integer()
    page = fields.Integer()
    per_page = fields.Integer()
    total_pages = fields.Integer()


# Availability Schemas

class AvailabilityQuerySchema(Schema):
    """Query parameters for availability check."""
    start = fields.String(required=True, 
                         metadata={"example": "2025-01-15T09:00:00Z",
                                  "description": "ISO 8601 datetime"})
    end = fields.String(required=True,
                       metadata={"example": "2025-01-15T10:00:00Z",
                                "description": "ISO 8601 datetime"})
    resource_type = fields.String(load_default=None)
    min_capacity = fields.Integer(load_default=None)
    location = fields.String(load_default=None)
    feature = fields.List(fields.String(), load_default=None)


class ResourceAvailabilitySchema(Schema):
    """Specific resource availability."""
    resource_id = fields.String(required=True)
    available = fields.Boolean(required=True)
    reason = fields.String()  # If not available, why
    conflicts = fields.List(fields.Nested('BookingSummarySchema'), load_default=None)
    next_available = fields.DateTime(format='iso')  # Next time it becomes available


class AvailableResourceSchema(Schema):
    """Resource with availability info."""
    resource = fields.Nested(ResourceSchema)
    available = fields.Boolean(required=True)
    conflicts = fields.List(fields.Nested('BookingSummarySchema'), load_default=None)


class AvailableResourcesResponseSchema(Schema):
    """List of available resources."""
    available_resources = fields.List(fields.Nested(AvailableResourceSchema))
    total_count = fields.Integer()


# Booking Schemas

class BookingSummarySchema(Schema):
    """Summary of a booking (for conflicts, etc.)."""
    booking_id = fields.String()
    event_id = fields.String()
    start = fields.DateTime(format='iso', required=True)
    end = fields.DateTime(format='iso', required=True)
    title = fields.String()
    organizer_id = fields.String()
    organizer_name = fields.String()
    status = fields.String()


class ResourceBookingSchema(Schema):
    """Full booking information."""
    id = fields.String()
    resource_id = fields.String()
    event_id = fields.String()
    start = fields.DateTime(format='iso', required=True)
    end = fields.DateTime(format='iso', required=True)
    status = fields.String()
    organizer_id = fields.String()
    organizer_name = fields.String()
    organizer_email = fields.String()
    booking_purpose = fields.String()
    approved_by = fields.String()
    approved_at = fields.DateTime(format='iso')
    created_at = fields.DateTime(format='iso')
    resource = fields.Nested(ResourceSchema)  # Optional: include resource details


class ResourceBookingsQuerySchema(Schema):
    """Query parameters for listing bookings."""
    start = fields.String(load_default=None)
    end = fields.String(load_default=None)
    status = fields.String(load_default=None)
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


# Create/Update Resource Schemas (Admin)

class ResourceCreateSchema(Schema):
    """Create a new resource."""
    name = fields.String(required=True)
    email = fields.Email(required=True)
    resource_type = fields.String(
        load_default="room",
        validate=validate.OneOf([t.value for t in ResourceTypeEnum])
    )
    description = fields.String(load_default="")
    capacity = fields.Integer(load_default=None, validate=validate.Range(min=1))
    location = fields.String(load_default=None)
    features = fields.List(fields.String(), load_default=None)
    is_active = fields.Boolean(load_default=True)
    booking_policy = fields.String(
        load_default="open",
        validate=validate.OneOf([p.value for p in BookingPolicyEnum])
    )
    allowed_groups = fields.List(fields.String(), load_default=None)
    auto_accept = fields.Boolean(load_default=True)


class ResourceUpdateSchema(Schema):
    """Update a resource."""
    name = fields.String()
    email = fields.Email()
    resource_type = fields.String(validate=validate.OneOf([t.value for t in ResourceTypeEnum]))
    description = fields.String()
    capacity = fields.Integer(validate=validate.Range(min=1))
    location = fields.String()
    features = fields.List(fields.String())
    is_active = fields.Boolean()
    booking_policy = fields.String(validate=validate.OneOf([p.value for p in BookingPolicyEnum]))
    allowed_groups = fields.List(fields.String())
    auto_accept = fields.Boolean()
```

---

## 7. Calendar Integration

Resources are booked by adding them as attendees to calendar events. This leverages the existing calendar event system.

### Resource attendee format:
```
ATTENDEE:mailtoresource:Conference Room A:resource@example.org
```

### Booking via Calendar Event Creation:

```python
# When creating/updating a calendar event with resource attendees:

def create_event_with_resources(event_data, user_id):
    # Create the event first
    event = calendar_module.create_event(
        start=event_data['start'],
        end=event_data['end'],
        title=event_data['title'],
        description=event_data['description'],
        organizer=user_id,
        attendees=event_data.get('attendees', [])
    )
    
    # Extract resource attendees
    resource_emails = []
    regular_attendees = []
    
    for attendee in event_data.get('attendees', []):
        if attendee.get('type') == 'resource' or attendee.get('email', '').startswith('resource-'):
            resource_emails.append(attendee['email'])
        else:
            regular_attendees.append(attendee)
    
    # Find resources by email
    resources = resource_module.get_by_emails(resource_emails)
    
    # Check availability
    conflicts = []
    for resource in resources:
        conflict = resource_module.check_availability(
            resource['id'],
            event['start'],
            event['end']
        )
        if not conflict['available']:
            conflicts.append(conflict)
    
    if conflicts:
        # Delete the event if there are conflicts
        calendar_module.delete_event(event['id'])
        raise ResourceConflictError(
            message="One or more resources are not available",
            conflicts=conflicts
        )
    
    # Create bookings for each resource
    for resource in resources:
        booking = resource_module.create_booking(
            event_id=event['id'],
            resource_id=resource['id'],
            start=event['start'],
            end=event['end'],
            organizer=user_id,
            booking_policy=resource['booking_policy']
        )
        
        # If moderated, send notification
        if resource['booking_policy'] == 'moderated' and not resource['auto_accept']:
            send_moderation_notification(resource, event, user_id)
    
    return event
```

### Conflict Detection:

The calendar system already has conflict detection. We extend it to check for resource-specific conflicts:

```python
# In CalendarAclEngine or ModuleCalendar:

def check_event_conflicts(event_data, user_id):
    """Check for all types of conflicts."""
    conflicts = []
    
    # 1. Regular calendar conflicts (busy times)
    user_conflicts = check_user_calendar_conflicts(event_data, user_id)
    conflicts.extend(user_conflicts)
    
    # 2. Resource conflicts
    resource_emails = extract_resource_emails(event_data.get('attendees', []))
    if resource_emails:
        resources = resource_module.get_by_emails(resource_emails)
        for resource in resources:
            resource_conflict = resource_module.check_availability(
                resource['id'],
                event_data['start'],
                event_data['end']
            )
            if not resource_conflict['available']:
                conflicts.extend(resource_conflict.get('conflicts', []))
    
    # 3. Room capacity conflicts (if applicable)
    
    return conflicts
```

---

## 8. Frontend Integration

### TypeScript API Client

```typescript
// sogo6-ui/src/features/resources/api.ts

import { http } from '@/lib/http';

export type ResourceType = 'room' | 'equipment' | 'vehicle' | 'other';
export type BookingPolicy = 'open' | 'moderated' | 'restricted';
export type BookingStatus = 'confirmed' | 'pending' | 'cancelled' | 'rejected';

export interface Resource {
  id: string;
  name: string;
  description: string;
  email: string;
  resource_type: ResourceType;
  capacity: number | null;
  location: string | null;
  features: string[];
  is_active: boolean;
  booking_policy: BookingPolicy;
  auto_accept: boolean;
  is_favorite: boolean;
  current_availability: string | null;
  next_available: string | null;
  created_at: string;
}

export interface ResourceBooking {
  id: string;
  resource_id: string;
  event_id: string;
  start: string;
  end: string;
  status: BookingStatus;
  organizer_id: string;
  organizer_name: string;
  booking_purpose?: string;
}

export interface Conflict {
  booking_id: string;
  event_id: string;
  start: string;
  end: string;
  title: string;
  organizer_name: string;
}

export interface AvailabilityCheck {
  resource_id: string;
  available: boolean;
  conflicts: Conflict[];
  next_available?: string;
}

const BASE_URL = '/api/v1/resources';
const ADMIN_BASE_URL = '/api/admin/v1/resources';

export const resourceApi = {
  // Resources
  list: (query?: { 
    resource_type?: ResourceType,
    min_capacity?: number,
    max_capacity?: number,
    location?: string,
    search?: string,
    feature?: string[],
    page?: number,
    per_page?: number
  }): Promise<{ resources: Resource[], total: number }> =>
    http.get(BASE_URL, { query }),
  
  get: (id: string): Promise<Resource> =>
    http.get(`${BASE_URL}/${id}`),
  
  search: (query: string, options?: { limit?: number }): Promise<Resource[]> =>
    http.get(`${BASE_URL}/search`, { query: { q: query, ...options } }),
  
  // Availability
  checkAvailability: (resourceId: string, start: string, end: string): Promise<AvailabilityCheck> =>
    http.post(`${BASE_URL}/${resourceId}/availability`, { start, end }),
  
  listAvailable: (start: string, end: string, options?: { 
    resource_type?: ResourceType,
    min_capacity?: number,
    location?: string,
    feature?: string[]
  }): Promise<{ available: Resource[], total: number }> =>
    http.get(`${BASE_URL}/available`, { query: { start, end, ...options } }),
  
  // Bookings
  listBookings: (resourceId: string, query?: { start?: string, end?: string, page?: number, per_page?: number }): Promise<{ bookings: ResourceBooking[], total: number }> =>
    http.get(`${BASE_URL}/${resourceId}/bookings`, { query }),
  
  // Favorites
  listFavorites: (): Promise<Resource[]> =>
    http.get(`${BASE_URL}/favorites`),
  
  addFavorite: (resourceId: string): Promise<void> =>
    http.post(`${BASE_URL}/favorites`, { resource_id: resourceId }),
  
  removeFavorite: (resourceId: string): Promise<void> =>
    http.delete(`${BASE_URL}/favorites/${resourceId}`),
  
  // Admin
  create: (data: Omit<Resource, 'id' | 'created_at'>): Promise<Resource> =>
    http.post(ADMIN_BASE_URL, data),
  
  update: (id: string, data: Partial<Resource>): Promise<Resource> =>
    http.patch(`${ADMIN_BASE_URL}/${id}`, data),
  
  delete: (id: string): Promise<void> =>
    http.delete(`${ADMIN_BASE_URL}/${id}`),
};
```

### Resource Picker Component

```tsx
// sogo6-ui/src/features/resources/ResourcePicker.tsx

import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Calendar, Clock, Users, Building, Car, Cpu, Search } from 'lucide-react';
import { Resource, ResourceType } from './api';
import { resourceApi } from './api';

const RESOURCE_TYPES: { value: ResourceType, label: string, icon: React.ReactNode }[] = [
  { value: 'room', label: 'Meeting Rooms', icon: <Building className="w-4 h-4" /> },
  { value: 'equipment', label: 'Equipment', icon: <Cpu className="w-4 h-4" /> },
  { value: 'vehicle', label: 'Vehicles', icon: <Car className="w-4 h-4" /> },
  { value: 'other', label: 'Other', icon: <Users className="w-4 h-4" /> },
];

interface ResourcePickerProps {
  start: string;
  end: string;
  selectedResources: string[];
  onSelect: (resourceId: string) => void;
  onDeselect: (resourceId: string) => void;
  minCapacity?: number;
  location?: string;
}

export function ResourcePicker({
  start,
  end,
  selectedResources,
  onSelect,
  onDeselect,
  minCapacity,
  location
}: ResourcePickerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTypes, setSelectedTypes] = useState<ResourceType[]>(['room']);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const loadAvailableResources = useCallback(async () => {
    setLoading(true);
    try {
      const { available } = await resourceApi.listAvailable(start, end, {
        resource_type: selectedTypes.join(','),
        min_capacity: minCapacity,
        location,
        search: searchQuery
      });
      setResources(available);
    } catch (err) {
      // Handle error
    } finally {
      setLoading(false);
    }
  }, [start, end, selectedTypes, minCapacity, location, searchQuery]);

  useEffect(() => {
    if (expanded) {
      loadAvailableResources();
    }
  }, [expanded, loadAvailableResources]);

  // Handle click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleType = (type: ResourceType) => {
    setSelectedTypes(prev => 
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    );
  };

  const getResourceIcon = (type: ResourceType) => {
    const t = RESOURCE_TYPES.find(rt => rt.value === type);
    return t?.icon || <Users className="w-4 h-4" />;
  };

  return (
    <div ref={containerRef} className="relative">
      <Button 
        variant="outline" 
        onClick={() => setExpanded(!expanded)}
        className="w-full justify-between"
      >
        <div className="flex items-center gap-2">
          <Building className="w-4 h-4" />
          <span>Add Resource ({selectedResources.length})</span>
        </div>
        {expanded ? '▲' : '▼'}
      </Button>

      {expanded && (
        <div className="absolute z-50 mt-1 w-80 bg-white rounded-lg shadow-lg border p-4">
          {/* Search */}
          <div className="relative mb-4">
            <Search className="absolute left-2 top-2.5 w-4 h-4 text-gray-500" />
            <Input 
              placeholder="Search resources..." 
              value={searchQuery} 
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8"
            />
          </div>

          {/* Type filters */}
          <div className="flex gap-2 mb-4 flex-wrap">
            {RESOURCE_TYPES.map(type => (
              <Button 
                key={type.value} 
                variant={selectedTypes.includes(type.value) ? 'default' : 'outline'} 
                size="sm" 
                onClick={() => toggleType(type.value)}
                className="h-7 px-2"
              >
                {type.icon}
                <span className="ml-1">{type.label}</span>
              </Button>
            ))}
          </div>

          {/* Resource list */}
          <div className="max-h-60 overflow-y-auto">
            {loading ? (
              <div className="text-center py-4 text-sm text-gray-500">Loading...</div>
            ) : resources.length === 0 ? (
              <div className="text-center py-4 text-sm text-gray-500">No resources available</div>
            ) : (
              <div className="space-y-2">
                {resources.map(resource => (
                  <div 
                    key={resource.id} 
                    className={`flex items-center gap-3 p-2 rounded cursor-pointer hover:bg-gray-50 ${
                      selectedResources.includes(resource.id) ? 'bg-blue-50 border border-blue-200' : ''
                    }`}
                    onClick={() => {
                      selectedResources.includes(resource.id) 
                        ? onDeselect(resource.id) 
                        : onSelect(resource.id);
                    }}
                  >
                    <div className="flex items-center gap-2 flex-1">
                      {getResourceIcon(resource.resource_type as ResourceType)}
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{resource.name}</div>
                        <div className="text-xs text-gray-500 truncate">
                          {resource.location} {resource.capacity && `• ${resource.capacity} people`}
                        </div>
                      </div>
                    </div>
                    <Checkbox 
                      checked={selectedResources.includes(resource.id)} 
                      onCheckedChange={(checked) => {
                        checked ? onSelect(resource.id) : onDeselect(resource.id);
                      }}
                      tabIndex={-1}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Selected resources */}
          {selectedResources.length > 0 && (
            <div className="mt-4 pt-3 border-t">
              <div className="text-sm font-medium mb-2">Selected:</div>
              <div className="flex flex-wrap gap-1">
                {selectedResources.map(id => {
                  const resource = resources.find(r => r.id === id);
                  return resource && (
                    <div key={id} className="flex items-center gap-1 bg-gray-100 rounded px-2 py-1 text-xs">
                      {getResourceIcon(resource.resource_type as ResourceType)}
                      <span>{resource.name}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

### Resource View Page

```tsx
// sogo6-ui/src/features/resources/ResourceViewPage.tsx

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { CalendarComponent } from '@/features/calendars';
import { Resource, ResourceBooking } from './api';
import { resourceApi } from './api';

export function ResourceViewPage() {
  const { id } = useParams();
  const [resource, setResource] = useState<Resource | null>(null);
  const [bookings, setBookings] = useState<ResourceBooking[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [r, b] = await Promise.all([
          resourceApi.get(id as string),
          resourceApi.listBookings(id as string, { 
            start: new Date().toISOString(),
            end: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString()
          })
        ]);
        setResource(r);
        setBookings(b.bookings);
      } catch (err) {
        // Handle error
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [id]);

  if (loading) return <div>Loading...</div>;
  if (!resource) return <div>Resource not found</div>;

  // Convert bookings to calendar events
  const events = bookings.map(booking => ({
    id: booking.event_id,
    title: `Booked: ${booking.organizer_name}`,
    start: booking.start,
    end: booking.end,
    status: booking.status,
    color: getBookingColor(booking.status),
    isBooking: true
  }));

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-bold">{resource.name}</h1>
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          resource.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
        }`}>
          {resource.is_active ? 'Available' : 'Inactive'}
        </span>
      </div>

      {/* Details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <p className="text-gray-600">{resource.description}</p>
        </div>
        <div className="space-y-2">
          <div className="flex gap-4">
            <div><span className="font-medium">Type:</span> <span>{resource.resource_type}</span></div>
            <div><span className="font-medium">Capacity:</span> <span>{resource.capacity || 'N/A'}</span></div>
          </div>
          <div><span className="font-medium">Location:</span> <span>{resource.location || 'N/A'}</span></div>
          <div><span className="font-medium">Policy:</span> <span>{resource.booking_policy}</span></div>
        </div>
      </div>

      {/* Features */}
      {resource.features && resource.features.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {resource.features.map(feature => (
            <span key={feature} className="px-2 py-1 bg-gray-100 rounded text-sm">
              {feature}
            </span>
          ))}
        </div>
      )}

      {/* Calendar */}
      <div className="mt-6">
        <h2 className="text-xl font-semibold mb-4">Schedule</h2>
        <CalendarComponent 
          events={events} 
          height="auto"
          readOnly
          showTime
        />
      </div>

      {/* Book Now Button */}
      <div className="mt-4">
        <Button onClick={() => { /* Open booking dialog */ }}>
          Book This Resource
        </Button>
      </div>
    </div>
  );
}

function getBookingColor(status: string) {
  switch (status) {
    case 'confirmed': return '#4CAF50';
    case 'pending': return '#FFC107';
    case 'cancelled': return '#9E9E9E';
    case 'rejected': return '#F44336';
    default: return '#2196F3';
  }
}
```

---

## 9. Resource Types Configuration

```yaml
# config/resources.yaml
resource_types:
  room:
    name: Meeting Room
    icon: building
    default_capacity: 10
    typical_features:
      - projector
      - video_conferencing
      - whiteboard
      - wheelchair_accessible
      - air_conditioning
    
  equipment:
    name: Equipment
    icon: cpu
    default_capacity: null
    typical_features:
      - portable
      - requires_setup
      - battery_powered
      
  vehicle:
    name: Vehicle
    icon: car
    default_capacity: 5
    typical_features:
      - gps
      - bluetooth
      - parking_sensor
      
  other:
    name: Other
    icon: tag
    default_capacity: null
    typical_features: []

booking_policies:
  open:
    name: Open
    description: Anyone in allowed groups can book instantly
    requires_approval: false
    
  moderated:
    name: Moderated
    description: Bookings require approval from resource owner
    requires_approval: true
    
  restricted:
    name: Restricted
    description: Only specific users can book
    requires_approval: false
```

---

## 10. Implementation Plan

### Phase 1: Backend Enhancement (Week 1-2)

1. **Complete existing implementation**
   - Review and test `ApiResourceBooking.py`
   - Review and test `ModuleResourceBooking.py`
   - Add missing features to module:
     - Booking tracking
     - Moderation support
     - Favorites management
   
2. **Add user-facing API**
   - Move admin-only endpoints to keep them separate
   - Add User API endpoints (non-admin)
   - Add favorites management
   - Add availability checking
   - Add booking queries
   
3. **Calendar integration**
   - Extend event creation to handle resources
   - Add resource conflict detection
   - Create bookings automatically from events
   - Update bookings when events change
   - Delete bookings when events deleted

### Phase 2: Frontend Implementation (Week 2-3)

1. **Resource picker component**
   - Search and filter
   - Availability checking
   - Multi-select
   
2. **Calendar integration**
   - Add resource picker to event creation
   - Show resource information in events
   - Color-code resource bookings
   
3. **Resource management pages**
   - Resource list (grid and list view)
   - Resource detail page
   - Resource calendar view
   
4. **Admin pages**
   - Resource CRUD
   - Bulk import
   - Analytics

### Phase 3: Advanced Features (Week 3-4)

1. **Conflict resolution**
   - Visual conflict indicators
   - Resolve conflicts UI
   - Override support
   
2. **Booking management**
   - View my bookings
   - Modify bookings
   - Cancel bookings
   
3. **Moderation flow**
   - Approve/reject bookings (admin)
   - Notifications
   - Approval workflow
   
4. **Performance**
   - Caching
   - Lazy loading
   - Virtual scrolling

### Phase 4: Testing & Polish

1. **Unit tests**
   - Module tests
   - API tests
   - Frontend tests
   
2. **Integration tests**
   - End-to-end flows
   - Conflict scenarios
   - Moderation scenarios
   
3. **Performance tests**
   - Load testing
   - Query optimization
   
4. **Documentation**
   - User guide
   - Admin guide
   - API docs updates

---

## 11. Success Criteria

- [ ] All admin API endpoints working
- [ ] User API endpoints for resource browsing
- [ ] Availability checking with conflict detection
- [ ] Calendar integration (add resources to events)
- [ ] Resource picker UI component
- [ ] Resource list and detail pages
- [ ] Favorites management
- [ ] Booking history per resource
- [ ] Booking history per user
- [ ] Moderation support for moderated resources
- [ ] Conflict resolution
- [ ] Performance: Sub-second response times
- [ ] Mobile Responsive UI
- [ ] Comprehensive test coverage
- [ ] Documentation

---

## 12. References

### Source Files
- `app/api/v1/admin/ApiResourceBooking.py` - Admin API
- `app/module/calendar/ModuleResourceBooking.py` - Backend module
- `app/module/calendar/model/CalResource.py` - Resource model

### Related Specifications
- `calendar.spec.md` - Core calendar functionality
- `admin.spec.md` - Admin operations
- `caldav.spec.md` - CalDAV support

---

## Appendix A: Default Features per Resource Type

| Type | Default Capacity | Typical Features |
|------|-----------------|------------------|
| Room | 10 | projector, video_conferencing, whiteboard, wheelchair_accessible, air_conditioning |
| Equipment | 1 | portable, requires_setup, battery_powered, heavy, fragile |
| Vehicle | 5 | gps, bluetooth, parking_sensor, child_seat, roof_rack |
| Other | null | |

---

## Appendix B: Booking Policy Matrix

```
┌─────────────────┬────────────┬─────────────────┬──────────────────┐
│   Policy        │ Auto-accept│ Requires Approval│ Who Can Book     │
├─────────────────┼────────────┼─────────────────┼──────────────────┤
│ Open           │ ✅ Yes      │ ❌ No           │ Any in groups    │
│ Moderated      │ ❌ No       │ ✅ Yes          │ Any in groups    │
│ Restricted     │ ✅ Yes      │ ❌ No           │ Specific users   │
└─────────────────┴────────────┴─────────────────┴──────────────────┘
```

---

## Appendix C: Error Codes

```
┌──────────────────────────┬────────┬─────────────────────┐
│   Error Code              │ HTTP   │   Description        │
├──────────────────────────┼────────┼─────────────────────┤
│ RESOURCE_NOT_FOUND        │ 404    │ Resource doesn't exist│
│ RESOURCE_INACTIVE         │ 400    │ Resource is deactivated│
│ CONFLICT_DETECTED         │ 409    │ Resource already booked│
│ MODERATION_REQUIRED      │ 403    │ Booking needs approval│
│ NOT_ALLOWED               │ 403    │ User can't book this │
│ PENDING_APPROVAL         │ 403    │ Waiting for approval│
│ INVALID_TIME_RANGE        │ 400    │ Invalid dates        │
│ CAPACITY_EXCEEDED         │ 400    │ Too many attendees   │
│ RATE_LIMITED             │ 429    │ Too many requests    │
└──────────────────────────┴────────┴─────────────────────┘
```

---

## Appendix D: Rate Limits

```
┌─────────────────────────┬────────────────┬──────────────┐
│   Endpoint               │ User          │ Admin        │
├─────────────────────────┼────────────────┼──────────────┤
│ List resources           │ 60/min         │ 120/min      │
│ Search resources         │ 30/min         │ 60/min       │
│ Check availability       │ 120/min        │ 240/min      │
│ List bookings            │ 60/min         │ 120/min      │
│ List favorites           │ 30/min         │ 30/min       │
│ Create resource          │ N/A            │ 10/min       │
│ Update resource          │ N/A            │ 20/min       │
│ Delete resource          │ N/A            │ 5/min        │
└─────────────────────────┴────────────────┴──────────────┘
```

---

**Document Status**: 📋 Draft / Specified  
**Author**: Tobias Weiss (@tobias-weiss-ai-xr)  
**Created**: 2025-08-20  
**Last Modified**: 2025-08-20  
**Target Implementation**: Q3-Q4 2025
