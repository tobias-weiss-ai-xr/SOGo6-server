# Resource Booking - Completion Implementation

## Change Metadata

| Field | Value |
|-------|-------|
| **Change ID** | resource-booking-completion |
| **Title** | Complete Resource Booking Feature Implementation |
| **Status** | Not Started |
| **Priority** | High (Tier 0) |
| **Type** | Feature Completion |
| **Created** | 2025-08-21 |
| **Author** | @tobias-weiss-ai-xr |
| **Assignee** | TBD |
| **Epic** | Tier 0 Foundation |
| **Spec** | [resource-booking.spec.md](../specs/resource-booking.spec.md) |
| **Compliance** | Current: 40% | Target: 100% |

---

## 📋 Overview

Complete the Resource Booking feature to meet 100% of specification requirements. Admin API exists but user API, frontend, and key features (availability checking with calendar integration, booking flow) are missing.

### Current Status

| Area | Status | Score |
|------|--------|-------|
| **Admin API** | ✅ Mostly Complete | 80% |
| **Data Models** | ✅ Mostly Complete | 80% |
| **Service Layer** | ⚠️ Partial | 40% |
| **Frontend (Admin)** | ❌ Missing | 0% |
| **Frontend (User)** | ❌ Missing | 0% |
| **User API** | ❌ Missing | 0% |
| **Tests** | ❌ Missing | 0% |
| **Documentation** | ⚠️ Partial | 50% |
| **Overall** | ⚠️ Partial | 40% |

### Related Artifacts

- **Specification**: [resource-booking.spec.md](../specs/resource-booking.spec.md)
- **Parent Change**: [tier0-implementation.change.md](./tier0-implementation.change.md)
- **Compliance Document**: [SPEC_IMPLEMENTATION_COMPLIANCE.md](../specs/SPEC_IMPLEMENTATION_COMPLIANCE.md)

---

## 🎯 Goals

### Primary Goals (Must Have - 100% Compliance)

1. ✅ **Admin API** - Already implemented
2. ⏳ **User API** - Implement `/user/v1/resources/*` endpoints
3. ⏳ **Frontend** - Create resource selection and booking UI
4. ⏳ **Calendar Integration** - Check availability against calendar
5. ⏳ **Booking Creation** - Implement bookable resources

### Secondary Goals (Should Have - 80% Compliance)

1. ⏳ **Conflict Detection** - Prevent double-booking
2. ⏳ **Notifications** - Email notifications for bookings
3. ⏳ **Moderation Workflow** - Approval system for restricted resources
4. ⏳ **Search** - Resource search and filtering
5. ⏳ **Favorites** - User's favorite resources

### Tertiary Goals (Nice to Have)

1. ⏳ **Analytics** - Resource usage statistics
2. ⏳ **Reports** - Booking reports and exports
3. ⏳ **Recurring Bookings** - Repeat booking patterns
4. ⏳ **Custom Fields** - Resource-specific metadata

---

## 📊 Requirements from Specification

### Current Implementation Discovery

**Backend Files**:
- `app/api/v1/admin/ApiResourceBooking.py` - Admin REST API (~230 lines)
- `app/module/calendar/ModuleResourceBooking.py` - Business logic
- `app/module/calendar/model/CalResource.py` - Data model

**Current API Endpoints** (from ApiResourceBooking.py):
- ✅ GET `/admin/v1/resources` - List all resources (with `active_only` filter)
- ✅ POST `/admin/v1/resources` - Create resource
- ✅ GET `/admin/v1/resources/{resource_id}` - Get resource by ID
- ✅ PATCH `/admin/v1/resources/{resource_id}` - Update resource
- ✅ DELETE `/admin/v1/resources/{resource_id}` - Delete resource
- ✅ GET `/admin/v1/resources/available` - List available resources in time window
- ✅ POST `/admin/v1/resources/{resource_id}/availability` - Check single resource availability

**Current Schema** (from ApiResourceBooking.py):
```python
class ResourceCreateSchema(Schema):
    name = fields.String(required=True)
    email = fields.Email(required=True)
    resource_type = fields.String(load_default="room", validate=validate.OneOf(["room", "equipment", "vehicle", "other"]))
    description = fields.String(load_default="")
    capacity = fields.Integer(load_default=None, validate=validate.Range(min=1))
    location = fields.String(load_default=None)
    features = fields.List(fields.String(), load_default=None)
    booking_policy = fields.String(load_default="open", validate=validate.OneOf(["open", "moderated", "restricted"]))
    allowed_groups = fields.List(fields.String(), load_default=None)
    auto_accept = fields.Boolean(load_default=True)
```

**CalResource.py Model**:
- ✅ Full dataclass with all fields
- ✅ `from_row()` and `to_dict()` methods
- ✅ Integration with calendar conflict detection
- ✅ Validation for resource types and booking policies

---

## 📁 Implementation Tasks

### Phase 1: User API 🎯 HIGH PRIORITY

**Description**: Create user-facing API for resource booking.

**Files to Create**:
- `app/api/v1/user/ApiResourceBooking.py`
- `app/module/user/ModuleUserResourceBooking.py`
- Table: `sogo6_resource_bookings`

**Required Endpoints** (from spec):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user/v1/resources` | List bookable resources user can access |
| GET | `/user/v1/resources/{resource_id}` | Get resource details |
| GET | `/user/v1/resources/available` | List available resources in time window |
| POST | `/user/v1/resources/{resource_id}/bookings` | Create a booking |
| GET | `/user/v1/resources/{resource_id}/bookings` | List user's bookings for resource |
| GET | `/user/v1/bookings` | List all user's bookings |
| GET | `/user/v1/bookings/{booking_id}` | Get booking details |
| PUT | `/user/v1/bookings/{booking_id}` | Update booking |
| DELETE | `/user/v1/bookings/{booking_id}` | Cancel booking |

**Database Schema**:
```sql
CREATE TABLE sogo6_resource_bookings (
    id VARCHAR(64) PRIMARY KEY,
    resource_id VARCHAR(64) NOT NULL,
    user_uid VARCHAR(256) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    title VARCHAR(256), 
    description TEXT,
    purpose TEXT,
    status VARCHAR(32) DEFAULT 'confirmed',  -- confirmed, pending, cancelled, rejected
    booking_policy VARCHAR(32) DEFAULT 'open',  -- open, moderated, restricted
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule TEXT,
    moderator_uid VARCHAR(256),
    moderator_notes TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (resource_id) REFERENCES sogo6_resources(id) ON DELETE CASCADE,
    CHECK (end_time > start_time)
);

CREATE INDEX idx_resource_bookings_resource_id ON sogo6_resource_bookings(resource_id);
CREATE INDEX idx_resource_bookings_user_uid ON sogo6_resource_bookings(user_uid);
CREATE INDEX idx_resource_bookings_start_time ON sogo6_resource_bookings(start_time);
CREATE INDEX idx_resource_bookings_end_time ON sogo6_resource_bookings(end_time);
```

**Acceptance Criteria**:
- [ ] All user API endpoints implemented
- [ ] Authentication and authorization working
- [ ] Only show resources user can access
- [ ] Booking creation with validation
- [ ] Conflict detection working

---

### Phase 2: Calendar Integration 🎯 HIGH PRIORITY

**Description**: Integrate resource availability with calendar to prevent double-booking.

**Files to Create/Modify**:
- `app/module/calendar/ModuleResourceBooking.py` (enhance)
- `app/module/user/ModuleUserResourceBooking.py`

**Implementation Notes**:

The current implementation in `ModuleResourceBooking.py` already mentions:
```python
# When a calendar event is created with a resource attendee,
# the calendar module's conflict detection prevents double-booking.
```

This means:
1. Resources have email addresses (e.g., room-a@example.org)
2. When booking a resource, create a calendar event with that email as attendee
3. Calendar's conflict detection prevents overlapping events
4. List available resources by checking calendar for conflicts

**Current `list_available` method** in ModuleResourceBooking:
- Takes start/end datetime
- Returns resources where no conflicting events exist

**Missing**:
- ❌ Component created when user booked
- ❌ Booking registration/ linking calendar events to bookings
- ❌ End- End user

---

### Phase 3: Admin UI 🎨 HIGH PRIORITY

**Description**: Create admin interface for resource management.

**Files to Create** (in sogo6-ui):
- `src/features/admin/resources/index.tsx`
- `src/features/admin/resources/components/ResourceList.tsx`
- `src/features/admin/resources/components/ResourceForm.tsx`
- `src/features/admin/resources/components/ResourceCalendar.tsx`
- `src/features/admin/resources/store/resource-api.ts`
- `src/app/[locale]/(loggedin)/admin/resources/page.tsx`

**Features**:
- [ ] List all resources with search/filter
- [ ] Create new resource
- [ ] Edit existing resource
- [ ] Delete resource
- [ ] View resource calendar/availability
- [ ] View resource bookings
- [ ] Manage moderation (for moderated/restricted resources)

---

### Phase 4: User UI 🎨 HIGH PRIORITY

**Description**: Create user interface for resource booking.

**Files to Create/Modify** (in sogo6-ui):
- `src/features/mails/components/ResourceBooking.tsx` (or new booking feature)
- `src/features/calendar/components/ResourceBookingOverlay.tsx`
- `src/features/calendar/components/ResourceSelector.tsx`

**Features**:
- [ ] Browse available resources
- [ ] Filter by type, capacity, features, location
- [ ] View resource availability (calendar view)
- [ ] Select time slot
- [ ] Add booking details (title, description, purpose)
- [ ] Submit booking request
- [ ] View my bookings
- [ ] Manage my bookings (edit, cancel)
- [ ] Add resources to favorites

---

### Phase 5: Core Features ⭐ HIGH PRIORITY

#### Task 5.1: Conflict Detection

**Description**: Ensure resources cannot be double-booked.

**Implementation**:
- Already partially implemented via calendar conflict detection
- Need to verify booking creation checks for conflicts
- Need to handle edge cases (back-to-back bookings, buffer times)

**Acceptance Criteria**:
- [ ] Cannot book overlapping time slots
- [ ] Cannot book during existing bookings
- [ ] Proper error messages for conflicts

#### Task 5.2: Notifications

**Files to Create**:
- `app/module/user/ModuleResourceBookingNotifications.py`

**Notification Types**:
- Booking confirmed
- Booking pending (moderated resources)
- Booking approved
- Booking rejected
- Booking cancelled
- Booking reminder (24 hours before)

**Acceptance Criteria**:
- [ ] All notification types implemented
- [ ] Emails sent to correct recipients
- [ ] Notifications configurable

#### Task 5.3: Moderation Workflow

**Description**: Implement approval system for moderated/restricted resources.

**Files to Create/Modify**:
- `app/api/v1/admin/ApiResourceBooking.py` (add moderation endpoints)
- `app/module/admin/ModuleResourceBooking.py` (add moderation logic)

**New Endpoints**:
- GET `/admin/v1/resource-bookings/pending` - List pending bookings
- POST `/admin/v1/resource-bookings/{booking_id}/approve` - Approve booking
- POST `/admin/v1/resource-bookings/{booking_id}/reject` - Reject booking
- POST `/admin/v1/resource-bookings/{booking_id}/cancel` - Cancel booking

**Acceptance Criteria**:
- [ ] Moderated resources require approval
- [ ] Admin can approve/reject bookings
- [ ] User notified of approval/rejection
- [ ] Restricted resources work correctly

---

### Phase 6: Enhanced Features ✨ MEDIUM PRIORITY

#### Task 6.1: Search and Filtering

**Description**: Allow users to search and filter resources.

**API Endpoints**:
- GET `/user/v1/resources?search={query}` - Search by name, description
- GET `/user/v1/resources?type=room` - Filter by type
- GET `/user/v1/resources?capacity_min=10` - Filter by capacity
- GET `/user/v1/resources?feature=projector` - Filter by feature
- GET `/user/v1/resources?location=Building+A` - Filter by location

**Acceptance Criteria**:
- [ ] Search works across all text fields
- [ ] All filters work individually and combined
- [ ] Performance acceptable with large datasets

#### Task 6.2: Favorites

**Database Schema**:
```sql
CREATE TABLE sogo6_user_resource_favorites (
    id VARCHAR(64) PRIMARY KEY,
    user_uid VARCHAR(256) NOT NULL,
    resource_id VARCHAR(64) NOT NULL,
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_uid) REFERENCES sogo6_users(uid) ON DELETE CASCADE,
    FOREIGN KEY (resource_id) REFERENCES sogo6_resources(id) ON DELETE CASCADE,
    UNIQUE (user_uid, resource_id)
);
```

**API Endpoints**:
- GET `/user/v1/resources/favorites` - List user's favorite resources
- POST `/user/v1/resources/{resource_id}/favorite` - Add to favorites
- DELETE `/user/v1/resources/{resource_id}/favorite` - Remove from favorites
- POST `/user/v1/resources/favorites/reorder` - Reorder favorites

---

### Phase 7: Nice to Have Features ✨ LOW PRIORITY

#### Task 7.1: Analytics

- Resource utilization statistics
- Most popular resources
- Booking frequency
- Total booking time

#### Task 7.2: Reports

- Export bookings to CSV
- Monthly usage reports
- Occupancy heatmaps

#### Task 7.3: Recurring Bookings

- Weekly, bi-weekly, monthly repeat patterns
- End date for recurring bookings
- Skip specific dates

#### Task 7.4: Custom Fields

- Add custom metadata fields to resources
- Different fields for different resource types
- Searchable custom fields

---

## 📄 Testing Requirements

### Unit Tests

- [ ] ModuleResourceBooking CRUD
- [ ] ModuleUserResourceBooking CRUD
- [ ] Conflict detection logic
- [ ] Availability checking
- [ ] Booking creation
- [ ] Moderation workflow
- [ ] Notification system

### Integration Tests

- [ ] Complete booking flow
- [ ] Calendar integration
- [ ] Conflict detection
- [ ] Moderation workflow
- [ ] Notification delivery

### E2E Tests

- [ ] User books a resource
- [ ] User views their bookings
- [ ] Admin manages resources
- [ ] Admin moderates bookings
- [ ] Conflict prevention

---

## 📝 Documentation Requirements

| Document | Location | Status |
|----------|----------|--------|
| Admin Guide | docs/admin/resource-booking.md | ❌ Missing |
| User Guide | docs/user/resource-booking.md | ❌ Missing |
| API Reference | docs/api/resource-booking.md | ❌ Missing |
| Configuration Guide | docs/admin/config/resource-booking.md | ❌ Missing |

---

## 🎯 Success Criteria

### 100% Compliance Checklist

- [ ] All API endpoints implemented
- [ ] All request/response schemas match spec
- [ ] All error codes implemented
- [ ] All data models match spec
- [ ] Calendar integration working
- [ ] Conflict detection working
- [ ] Notifications working
- [ ] Moderation workflow working
- [ ] All frontend components working
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All E2E tests pass
- [ ] All documentation complete

---

## 📊 Estimates

| Task | Complexity | Estimate | Priority |
|------|------------|----------|----------|
| User API | Medium | 3-4 days | High |
| Calendar integration | Medium | 2-3 days | High |
| Admin UI | Medium | 4-5 days | High |
| User UI | Medium | 4-5 days | High |
| Conflict detection | Low | 1-2 days | High |
| Notifications | Medium | 2-3 days | High |
| Moderation workflow | Medium | 2 days | High |
| Search & filtering | Medium | 2 days | Medium |
| Favorites | Low | 1 day | Medium |
| Analytics | Medium | 2 days | Low |
| Reports | Medium | 2 days | Low |
| Recurring bookings | High | 3-4 days | Low |
| Custom fields | Medium | 2 days | Low |
| Unit tests | Medium | 3 days | High |
| Integration tests | Medium | 2 days | High |
| E2E tests | Medium | 2 days | High |
| Documentation | Medium | 2 days | Medium |
| **Total** | | **~6-8 weeks** | |

---

## 🔗 Dependencies

### Blocked By
- Calendar module (for conflict detection)
- Existing calendar conflict detection must be working

### Blocks
- Team Calendars (similar calendar integration patterns)

### Related Changes
- [tier0-implementation.change.md](./tier0-implementation.change.md)
- [resource-booking.change.md](./resource-booking.change.md)

---

## 📞 Contacts

| Role | Person | Contact |
|------|--------|---------|
| **Architect** | Tobias Weiss | @tobias-weiss-ai-xr |
| **Tech Lead** | TBD | TBD |

---

## 📅 Timeline

### Milestones

| Date | Milestone | Deliverables |
|------|-----------|--------------|
| Week 1 | User API | ApiResourceBooking.py, ModuleUserResourceBooking.py |
| Week 2 | Calendar Integration | Conflict detection, booking creation |
| Week 3-4 | Admin UI | All admin UI components |
| Week 5-6 | User UI | Resource selection, booking flow |
| Week 7 | Core Features | Notifications, moderation |
| Week 8 | Enhanced Features | Search, favorites |
| Week 9 | Testing & Docs | All tests, documentation |

---

## 🔄 Change Log

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2025-08-21 | 1.0.0 | @tobias-weiss-ai-xr | Initial change file created |

---

**Change Status**: 📝 Specified / Not Started  
**Last Updated**: 2025-08-21
