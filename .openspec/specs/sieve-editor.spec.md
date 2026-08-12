# Sieve Editor UI Specification

## Overview

This specification defines the **Sieve Editor UI** feature for SOGo 6, providing a visual, drag-and-drop interface for creating and managing email filters. This builds on the existing `ClientSieve.py` backend implementation and the frontend components in `sogo6-ui/src/features/user-settings/mail/filters/`.

**Status**: ⚠️ Partially Implemented (Backend: ✅ | Frontend: 📋 | Integration: ❌)
**Version**: 1.0.0
**Priority**: Tier 0 (Foundation)
**Effort**: Medium (4-6 weeks)
**Dependencies**:
- Existing Sieve backend (`ClientSieve.py`) - ✅ Complete
- Frontend filter components - 📋 In Progress

---

## Table of Contents

1. [Background](#background)
2. [Goals](#goals)
3. [Features](#features)
4. [Architecture](#architecture)
5. [API Design](#api-design)
6. [Data Models](#data-models)
7. [Frontend Components](#frontend-components)
8. [Backend Integration](#backend-integration)
9. [Implementation Plan](#implementation-plan)
10. [Testing](#testing)

---

## Background

### Current State

The SOGo 6 project currently has:

**Backend (✅ Complete):**
- `ClientSieve.py`: Full Sieve client implementation with ManageSieve support
- Error codes: `ERROR_SIEVE_*` for all Sieve operations
- Filter schemas: `app/api/v1/mail/schemas/filter.py`
- Filter API: Partial implementation in mail module

**Frontend (📋 In Progress):**
- Filter settings page: `sogo6-ui/src/features/user-settings/mail/filters/`
- Filter components: Form, schema, utilities
- Fake API: mocked endpoints for development

**Missing:**
- Full REST API for filter management
- Integration between frontend and backend
- Visual drag-and-drop builder (beyond basic form)
- Real-time filter validation
- Filter testing/preview functionality

### Gap Analysis

The Sieve Editor UI needs:
1. A complete REST API for CRUD operations on filters
2. Integration with the existing `ClientSieve.py` backend
3. Enhanced frontend with drag-and-drop interface
4. Real-time validation and preview
5. User-friendly error handling

---

## Goals

### Primary Goals

1. **Visual Filter Builder**: Drag-and-drop interface for creating complex filter rules
2. **Rule Templates**: Predefined filter templates for common use cases
3. **Real-time Validation**: Validate Sieve syntax before saving
4. **Filter Testing**: Preview which emails will match a filter
5. **Full CRUD API**: RESTful API for filter management
6. **Multi-Account Support**: Manage filters for multiple mail accounts

### Secondary Goals

1. **Advanced Conditions**: Support for complex Boolean logic (AND/OR/NOT)
2. **Custom Actions**: Support for all Sieve actions (fileinto, redirect, reject, etc.)
3. **Filter Ordering**: UI for reordering filter execution
4. **Filter Sharing**: Share filters with other users (future)
5. **Import/Export**: Import and export filters as Sieve scripts

---

## Features

### Core Features (Must Have)

#### Filter Management
- [ ] List all filters for an account
- [ ] Create new filter
- [ ] Update existing filter
- [ ] Delete filter
- [ ] Reorder filters (execution order)
- [ ] Enable/disable individual filters
- [ ] Bulk enable/disable filters

#### Rule Building
- [ ] Visual condition builder
- [ ] Field selection (From, To, Subject, Body, Headers, etc.)
- [ ] Operator selection (contains, equals, matches, regex, etc.)
- [ ] Value input with autocomplete
- [ ] Add/remove conditions
- [ ] Group conditions (AND/OR logic)
- [ ] Negation (NOT logic)

#### Action Configuration
- [ ] Move to folder (fileinto)
- [ ] Copy to folder (fileinto with :copy flag)
- [ ] Forward to address (redirect)
- [ ] Discard message
- [ ] Mark as read
- [ ] Flag message
- [ ] Add tag/label
- [ ] Stop processing (stop)
- [ ] Multiple actions per filter

#### User Experience
- [ ] Drag-and-drop rule builder
- [ ] Real-time syntax validation
- [ ] Filter preview (show matching emails)
- [ ] Undo/redo support
- [ ] Save as draft
- [ ] Auto-save

#### Integration
- [ ] List available folders for fileinto actions
- [ ] Validate email addresses for redirect actions
- [ ] Check folder existence before saving
- [ ] Push filters to Sieve server
- [ ] Handle Sieve server errors gracefully

### Advanced Features (Nice to Have)

#### Advanced Conditions
- [ ] Message size (larger than, smaller than)
- [ ] Date range (before, after, between)
- [ ] Attachment presence
- [ ] Spam status
- [ ] Read/unread status
- [ ] Flagged status
- [ ] Custom headers
- [ ] Regular expressions

#### Advanced Actions
- [ ] Send notification (enotify extension)
- [ ] Add to address book
- [ ] Execute script (vnd.dovecot.execute extension)
- [ ] Set IMAP flags (imap4flags extension)
- [ ] Custom Sieve extensions (if supported by server)

#### Premium Features
- [ ] Filter templates library
- [ ] Filter sharing between users
- [ ] Filter versioning
- [ ] Filter analytics (how many emails matched)
- [ ] Scheduled filters (run at specific times)

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (React/Next.js)                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Sieve Editor UI                                 ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                ││
│  │  │ Filter   │  │ Rule     │  │ Filter   │                ││
│  │  │ List     │  │ Builder  │  │ Preview  │                ││
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                ││
│  │       │             │             │                        ││
│  └───────┼─────────────┼─────────────┼────────────────────────┘│
│          │             │             │                          │
│          ▼             ▼             ▼                          │
└──────────┼─────────────┼─────────────┼──────────────────────────┘
           │             │             │
           └─────────────┼─────────────┘
                     │ (API Calls)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend (Flask/Python)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Filter API                                      ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                ││
│  │  │ GET      │  │ POST     │  │ PUT      │                ││
│  │  │ /filters │  │ /filters │  │ /filters/│                ││
│  │  │          │  │          │  │ {id}     │                ││
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                ││
│  │       │             │             │                        ││
│  └───────┼─────────────┼─────────────┼────────────────────────┘│
│          │             │             │                          │
│          ▼             ▼             ▼                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              Filter Service                                  ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     ││
│  │  │ Validator    │  │ Compiler     │  │ Sieve Client │     ││
│  │  │              │  │              │  │ (ClientSieve)│     ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘     ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Existing Sieve Infrastructure                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              ManageSieve Server (Dovecot)                   ││
│  │  - Script storage                                           ││
│  │  - Script activation                                        ││
│  │  - Capability detection                                     ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Component Directory Structure

```
sogo6-ui/src/features/user-settings/mail/filters/
├── index.tsx                          # Main entry point
├── mail-filters-api-types.ts         # API types
├── mail-filters-constants.ts         # Constants (operators, fields, etc.)
├── mail-filters-types.ts             # TypeScript types
├── mail-filters-utils.ts             # Utility functions
├── store/
│   ├── mail-filters-settings-api.ts  # API client
│   └── mail-filters-slice.ts         # Redux slice (if using Redux)
├── components/
│   ├── filters-form.tsx              # Main form component
│   ├── filters-form-core.tsx         # Core form logic
│   ├── filter-line-form.tsx          # Single filter rule component
│   ├── filters-skeleton.tsx          # Loading skeleton
│   ├── drag-drop-builder.tsx         # NEW: Drag-and-drop builder
│   ├── rule-builder.tsx              # NEW: Rule building interface
│   ├── condition-builder.tsx         # NEW: Condition components
│   ├── action-builder.tsx            # NEW: Action components
│   ├── filter-list.tsx               # NEW: Filter list with reordering
│   ├── filter-preview.tsx            # NEW: Preview component
│   ├── filter-templates.tsx          # NEW: Template library
│   └── validation-error.tsx          # NEW: Error display
└── __tests__/
    ├── *.test.tsx                     # Component tests
    └── *.test.ts                      # Utility tests

sogo6-server/app/api/v1/mail/
├── ApiFilters.py                      # NEW: Filter REST API
└── schemas/
    └── filter.py                      # Existing + enhanced
```

---

## API Design

### RESTful Endpoints

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| GET | `/api/v1/mailboxes/{accountId}/filters` | List all filters | ⚠️ Existing (fake) |
| POST | `/api/v1/mailboxes/{accountId}/filters` | Create new filter | ❌ To Implement |
| GET | `/api/v1/mailboxes/{accountId}/filters/{filterId}` | Get single filter | ❌ To Implement |
| PUT | `/api/v1/mailboxes/{accountId}/filters/{filterId}` | Update filter | ❌ To Implement |
| DELETE | `/api/v1/mailboxes/{accountId}/filters/{filterId}` | Delete filter | ❌ To Implement |
| PATCH | `/api/v1/mailboxes/{accountId}/filters/reorder` | Reorder filters | ❌ To Implement |
| POST | `/api/v1/mailboxes/{accountId}/filters/validate` | Validate filter | ❌ To Implement |
| POST | `/api/v1/mailboxes/{accountId}/filters/preview` | Preview matches | ❌ To Implement |
| POST | `/api/v1/mailboxes/{accountId}/filters/push` | Push to Sieve | ❌ To Implement |
| GET | `/api/v1/mailboxes/{accountId}/filters/templates` | List templates | ❌ To Implement |

### Request/Response Schemas

#### Filter Schema

```typescript
// TypeScript type definition
interface FilterRuleCondition {
  // Basic condition
  field: 'from' | 'to' | 'cc' | 'bcc' | 'subject' | 'body' | 'header' | 'size' | 'date';
  operator: 'contains' | 'not_contains' | 'equals' | 'not_equals' | 'matches' | 'not_matches' | 'regex' | 'not_regex';
  value: string;
  
  // Custom header (when field === 'header')
  custom_header?: string;
  
  // Size operators
  size_operator?: 'greater_than' | 'less_than';
  
  // Date operators
  date_field?: 'received' | 'sent' | 'modified';
  date_operator?: 'before' | 'after' | 'on' | 'between';
  date_value_start?: string;  // ISO 8601
  date_value_end?: string;    // ISO 8601
}

interface FilterRuleGroup {
  op: 'and' | 'or' | 'not';
  rules: Array<FilterRuleCondition | FilterRuleGroup>;
}

interface FilterAction {
  method: 'fileinto' | 'redirect' | 'discard' | 'keep' | 'stop' | 'flag' | 'mark' | 'add_tag';
  arguments: {
    // For fileinto
    folders?: string[];
    create_if_no_exist?: boolean;
    keep_copy?: boolean;
    
    // For redirect
    addresses?: string[];
    
    // For flag
    flag?: 'flagged' | 'unflagged';
    
    // For mark
    mark?: 'read' | 'unread';
    
    // For add_tag
    tags?: string[];
  };
}

interface Filter {
  id: string;  // Server-assigned UUID
  name: string;
  enabled: boolean;
  priority: number;  // Execution order (lower = earlier)
  rules: FilterRuleGroup;
  actions: FilterAction[];
  created_at: string;  // ISO 8601
  updated_at: string;  // ISO 8601
  error?: string;      // Last error message (if validation failed)
}

// API Response types
interface FilterListResponse {
  error_code: string;
  error_msg: string;
  data: {
    filters: Filter[];
    total_count: number;
    // For server capabilities
    sieve_capabilities: string[];
    max_filters: number;
  };
}

interface FilterSingleResponse {
  error_code: string;
  error_msg: string;
  data: {
    filter: Filter;
    // Additional metadata for the UI
    available_folders: string[];
    available_tags: string[];
  };
}

interface ValidationResponse {
  error_code: string;
  error_msg: string;
  data: {
    valid: boolean;
    errors?: Array<{
      field: string;
      message: string;
      severity: 'error' | 'warning';
    }>;
    sieve_script: string;  // Generated Sieve script (for debugging)
  };
}

interface PreviewResponse {
  error_code: string;
  error_msg: string;
  data: {
    preview: Array<{
      message_id: string;
      subject: string;
      from: string;
      received_at: string;
    }>;
    total_matches: number;
    sample_size: number;
  };
}

interface PushResponse {
  error_code: string;
  error_msg: string;
  data: {
    success: boolean;
    message: string;
    activated: boolean;
    skipped_sections?: string[];  // If some sections couldn't be pushed
  };
}
```

#### Example Requests

**List Filters:**
```http
GET /api/v1/mailboxes/0/filters HTTP/1.1
Authorization: Bearer <token>
```

**Response:**
```json
{
  "error_code": "S000000",
  "error_msg": "No Error",
  "data": {
    "filters": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Newsletters",
        "enabled": true,
        "priority": 1,
        "rules": {
          "op": "and",
          "rules": [
            {
              "field": "subject",
              "operator": "contains",
              "value": "newsletter"
            }
          ]
        },
        "actions": [
          {
            "method": "fileinto",
            "arguments": {
              "folders": ["Newsletters"],
              "create_if_no_exist": true
            }
          }
        ],
        "created_at": "2025-01-01T12:00:00Z",
        "updated_at": "2025-01-01T12:00:00Z"
      }
    ],
    "total_count": 1,
    "sieve_capabilities": ["fileinto", "redirect", "reject", "imap4flags", "copy", "mailbox", "notify", "enotify", "body", "date", "index", "relational", "regex", "subaddress", "vnd.dovecot.pipe", "vnd.dovecot.environment", "+notify"],
    "max_filters": 100
  }
}
```

**Create Filter:**
```http
POST /api/v1/mailboxes/0/filters HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Work Emails",
  "enabled": true,
  "priority": 1,
  "rules": {
    "op": "or",
    "rules": [
      {"field": "from", "operator": "contains", "value": "@company.com"},
      {"field": "to", "operator": "contains", "value": "@company.com"}
    ]
  },
  "actions": [
    {
      "method": "fileinto",
      "arguments": {"folders": ["Work"], "create_if_no_exist": true}
    },
    {"method": "mark", "arguments": {"mark": "read"}}
  ]
}
```

**Validate Filter:**
```http
POST /api/v1/mailboxes/0/filters/validate HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Test Filter",
  "rules": {
    "op": "and",
    "rules": [
      {"field": "subject", "operator": "contains", "value": "test"}
    ]
  },
  "actions": [
    {"method": "discard", "arguments": {}}
  ]
}
```

**Reorder Filters:**
```http
PATCH /api/v1/mailboxes/0/filters/reorder HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json

{
  "filter_order": [
    "550e8400-e29b-41d4-a716-446655440000",
    "550e8400-e29b-41d4-a716-446655440001",
    "550e8400-e29b-41d4-a716-446655440002"
  ]
}
```

---

## Data Models

### Backend Models

```python
# sogo6-server/app/api/v1/mail/schemas/filter.py

from marshmallow import Schema, fields, validate, ValidationError
from typing import List, Dict, Any, Optional, Union

class FilterConditionSchema(Schema):
    """Schema for a single filter condition."""
    field = fields.String(
        required=True,
        validate=validate.OneOf([
            'from', 'to', 'cc', 'bcc', 'subject', 'body', 'header',
            'size', 'date', 'flagged', 'read', 'attachment'
        ]),
        metadata={"description": "Field to filter on"}
    )
    operator = fields.String(
        required=True,
        validate=validate.OneOf([
            'contains', 'not_contains', 'equals', 'not_equals',
            'matches', 'not_matches', 'regex', 'not_regex'
        ]),
        metadata={"description": "Comparison operator"}
    )
    value = fields.String(required=False, load_default="", metadata={"description": "Value to match"})
    
    # Custom header field
    custom_header = fields.String(
        required=False,
        metadata={"description": "Custom header name (when field='header')"}
    )
    
    # Size operators
    size_operator = fields.String(
        required=False,
        validate=validate.OneOf(['greater_than', 'less_than']),
        metadata={"description": "Size comparison (when field='size')"}
    )
    
    # Date operators
    date_field = fields.String(
        required=False,
        validate=validate.OneOf(['received', 'sent', 'modified']),
        metadata={"description": "Which date to filter (when field='date')"}
    )
    date_operator = fields.String(
        required=False,
        validate=validate.OneOf(['before', 'after', 'on', 'between']),
        metadata={"description": "Date comparison operator"}
    )
    date_value_start = fields.DateTime(
        required=False,
        format='iso',
        metadata={"description": "Start date (for 'between' or 'after')"}
    )
    date_value_end = fields.DateTime(
        required=False,
        format='iso',
        metadata={"description": "End date (for 'between' or 'before')"}
    )


class FilterRuleGroupSchema(Schema):
    """Recursive schema for filter rule groups."""
    op = fields.String(
        required=True,
        validate=validate.OneOf(['and', 'or', 'not']),
        metadata={"description": "Logical operator"}
    )
    rules = fields.List(
        fields.Nested(lambda: Union[FilterConditionSchema, 'FilterRuleGroupSchema']),
        required=True,
        metadata={"description": "List of nested rules"}
    )


class FilterActionSchema(Schema):
    """Schema for a filter action."""
    method = fields.String(
        required=True,
        validate=validate.OneOf([
            'fileinto', 'redirect', 'discard', 'keep', 'stop',
            'flag', 'mark', 'add_tag', 'remove_tag'
        ]),
        metadata={"description": "Action method"}
    )
    arguments = fields.Dict(
        required=False,
        metadata={"description": "Action-specific arguments"}
    )


class FilterSchema(Schema):
    """Schema for a complete filter."""
    id = fields.String(
        dump_only=True,
        metadata={"description": "Server-assigned UUID"}
    )
    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=255),
        metadata={"description": "Filter name"}
    )
    enabled = fields.Boolean(
        required=False,
        load_default=True,
        metadata={"description": "Whether filter is enabled"}
    )
    priority = fields.Integer(
        required=False,
        load_default=0,
        metadata={"description": "Execution priority (lower = earlier)"}
    )
    rules = fields.Nested(
        FilterRuleGroupSchema,
        required=True,
        metadata={"description": "Filter conditions"}
    )
    actions = fields.List(
        fields.Nested(FilterActionSchema),
        required=True,
        validate=validate.Length(min=1),
        metadata={"description": "Filter actions"}
    )
    created_at = fields.DateTime(
        dump_only=True,
        format='iso',
        metadata={"description": "Creation timestamp"}
    )
    updated_at = fields.DateTime(
        dump_only=True,
        format='iso',
        metadata={"description": "Last update timestamp"}
    )


class FilterListSchema(Schema):
    """Schema for listing filters."""
    filters = fields.List(fields.Nested(FilterSchema))
    total_count = fields.Integer()
    sieve_capabilities = fields.List(fields.String())
    max_filters = fields.Integer()


class FilterValidationSchema(Schema):
    """Schema for filter validation."""
    name = fields.String(required=False)
    rules = fields.Nested(FilterRuleGroupSchema, required=True)
    actions = fields.List(
        fields.Nested(FilterActionSchema),
        required=True,
        validate=validate.Length(min=1)
    )
```

---

## Frontend Components

### Component Hierarchy

```
┌─────────────────────────────────────────────────────────┐
│                    <MailFiltersSettings>                 │
│  Main container for sieve editor                         │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────┐  ┌─────────────────┐ │
│  │     <FilterList>             │  │   <FilterForm>  │ │
│  │  - List of all filters       │  │   - Create/Edit │ │
│  │  - Enable/disable toggles    │  │   - Drag-drop    │ │
│  │  - Reorder (drag-drop)        │  │   - Validate    │ │
│  │  - Delete                    │  │   - Preview     │ │
│  │  - Duplicate                 │  │   - Save        │ │
│  │  - Edit                      │  │                 │ │
│  └──────────────┬───────────────┘  └────────┬─────────┘ │
│                 │                              │          │
│                 ▼                              ▼          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                 <FilterPreview>                        │ │
│  │  - Show matching emails (sample)                     │ │
│  │  - Match count estimation                            │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Component Specifications

#### 1. FilterList Component

**Responsibilities:**
- Display all filters for the current account
- Show filter status (enabled/disabled)
- Allow reordering via drag-and-drop
- Enable/disable filters with toggle switches
- Delete filters with confirmation
- Edit filters (opens FilterForm in edit mode)
- Duplicate filters
- Show filter creation date

**Props:**
```typescript
interface FilterListProps {
  filters: Filter[];
  onEdit: (filter: Filter) => void;
  onDelete: (filterId: string) => void;
  onReorder: (newOrder: string[]) => void;
  onToggle: (filterId: string, enabled: boolean) => void;
  onDuplicate: (filter: Filter) => void;
  onCreateNew: () => void;
  isLoading: boolean;
  error?: string;
  maxFilters: number;
}
```

**Features:**
- Virtualized list for performance (100+ filters)
- Bulk actions (enable/disable all, delete selected)
- Search/filter by name
- Sort by name, priority, creation date
- Drag-and-drop reordering with visual feedback
- Responsive design (desktop + mobile)

#### 2. FilterForm Component

**Responsibilities:**
- Create new filter or edit existing
- Visual rule builder with drag-and-drop
- Action configuration
- Real-time validation
- Filter preview
- Save with confirmation
- Auto-save draft

**Props:**
```typescript
interface FilterFormProps {
  filter?: Filter;  // null for new filter
  availableFolders: string[];
  availableTags: string[];
  sieveCapabilities: string[];
  onSave: (filter: Filter) => void;
  onCancel: () => void;
  onValidate: (filter: Partial<Filter>) => boolean;
  onPreview: (filter: Partial<Filter>) => Promise<PreviewResponse>;
  isLoading: boolean;
  error?: string;
}
```

**Sub-Components:**
- `FilterNameInput`: Filter name field
- `RuleBuilder`: Drag-and-drop condition builder
- `ActionBuilder`: Action configuration
- `ValidationDisplay`: Show validation errors
- `PreviewPanel`: Show filter preview
- `SaveButton`: Save with validation

#### 3. RuleBuilder Component

**Responsibilities:**
- Visual condition building
- Support for nested conditions (AND/OR/NOT)
- Field selection with autocomplete
- Operator selection
- Value input with field-specific UI
- Add/remove/duplicate rules
- Drag-and-drop reordering

**Props:**
```typescript
interface RuleBuilderProps {
  rules: FilterRuleGroup;
  onChange: (rules: FilterRuleGroup) => void;
  availableFields: Array<{
    value: string;
    label: string;
    description?: string;
  }>;
  availableOperators: Array<{
    value: string;
    label: string;
    applicableFields: string[];
  }>;
}
```

**Features:**
- Tree view of nested conditions
- Add new condition or group
- Convert condition to group (and vice versa)
- Drag-and-drop reordering of conditions
- Delete conditions with confirmation
- Field-specific value inputs (email, text, date picker, etc.)
- Autocomplete for known values (domains, contacts)

#### 4. ActionBuilder Component

**Responsibilities:**
- Action selection and configuration
- Multiple actions per filter
- Action-specific UI
- Validation

**Props:**
```typescript
interface ActionBuilderProps {
  actions: FilterAction[];
  onChange: (actions: FilterAction[]) => void;
  availableFolders: string[];
  sieveCapabilities: string[];
}
```

**Features:**
- Add new action dropdown
- Configure each action based on type
- Reorder actions
- Delete actions
- Show capability requirements

#### 5. FilterPreview Component

**Responsibilities:**
- Show preview of matching emails
- Allow testing with different date ranges
- Show match count estimate
- Quick preview without saving

**Props:**
```typescript
interface FilterPreviewProps {
  filter: Partial<Filter>;
  onRefresh: () => void;
  preview?: PreviewResponse;
  isLoading: boolean;
  error?: string;
}
```

**Features:**
- Sample of matching emails (subject, from, date)
- Total match count
- Estimation (if full scan is expensive)
- Refresh button
- Date range selector for testing

---

## Backend Integration

### Service Layer

```python
# sogo6-server/app/service/FilterService.py

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import uuid
import time

from app.manager.mail.ClientSieve import ClientSieve
from app.utils import errors as err
from app.utils.exceptions import RequestException


@dataclass
class Filter:
    id: str
    name: str
    enabled: bool
    priority: int
    rules: Dict[str, Any]
    actions: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    error: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool
    errors: List[Dict[str, Any]]
    sieve_script: Optional[str] = None


@dataclass
class PreviewResult:
    matches: List[Dict[str, Any]]
    total_count: int


class FilterService:
    """Service for managing email filters."""
    
    def __init__(self, user_id: str, sieve_client: ClientSieve):
        self.user_id = user_id
        self.sieve_client = sieve_client
    
    async def get_filters(self, account_id: str) -> List[Filter]:
        """Get all filters for an account."""
        # Fetch from database
        # Return as Filter objects
        pass
    
    async def get_filter(self, filter_id: str) -> Optional[Filter]:
        """Get a single filter by ID."""
        pass
    
    async def create_filter(self, filter_data: Dict[str, Any]) -> Filter:
        """Create a new filter."""
        filter_id = str(uuid.uuid4())
        filter = Filter(
            id=filter_id,
            name=filter_data['name'],
            enabled=filter_data.get('enabled', True),
            priority=filter_data.get('priority', 0),
            rules=filter_data['rules'],
            actions=filter_data['actions'],
            created_at=time.time(),
            updated_at=time.time()
        )
        
        # Validate
        validation = await self.validate_filter(filter)
        if not validation.valid:
            filter.error = "; ".join([e['message'] for e in validation.errors])
            return filter
        
        # Save to database
        # Push to Sieve server if enabled
        if filter.enabled:
            await self.push_to_sieve([filter])
        
        return filter
    
    async def update_filter(self, filter_id: str, filter_data: Dict[str, Any]) -> Optional[Filter]:
        """Update an existing filter."""
        pass
    
    async def delete_filter(self, filter_id: str) -> bool:
        """Delete a filter."""
        pass
    
    async def reorder_filters(self, filter_ids: List[str]) -> bool:
        """Reorder filters by updating their priorities."""
        for index, filter_id in enumerate(filter_ids):
            # Update priority in database
            pass
        
        # Push all enabled filters to Sieve
        enabled_filters = await self.get_enabled_filters()
        await self.push_to_sieve(enabled_filters)
        return True
    
    async def validate_filter(self, filter: Filter) -> ValidationResult:
        """Validate a filter's rules and actions."""
        errors = []
        
        # Validate rules
        rule_errors = self._validate_rules(filter.rules)
        if rule_errors:
            errors.extend(rule_errors)
        
        # Validate actions
        action_errors = self._validate_actions(filter.actions)
        if action_errors:
            errors.extend(action_errors)
        
        # Generate Sieve script for debugging
        sieve_script = None
        if not errors:
            try:
                sieve_script = self._compile_to_sieve(filter)
            except Exception as e:
                errors.append({
                    'field': 'sieve_compilation',
                    'message': f'Failed to compile to Sieve: {str(e)}',
                    'severity': 'error'
                })
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            sieve_script=sieve_script
        )
    
    async def preview_filter(self, filter: Filter, limit: int = 10) -> PreviewResult:
        """Preview which emails would match a filter."""
        # This could query the mail store directly or use a search index
        # For performance, might need to limit to recent emails or sample
        
        # For now, return mock data
        return PreviewResult(
            matches=[],
            total_count=0
        )
    
    async def push_to_sieve(self, filters: List[Filter]) -> Dict[str, Any]:
        """Push filters to the Sieve server."""
        try:
            # Get all enabled filter sections
            filters_config = {
                'filters': [
                    {'name': f.name, 'enabled': f.enabled, 'rules': f.rules, 'actions': f.actions}
                    for f in filters if f.enabled
                ]
            }
            
            # Use existing ClientSieve.set_merged_filters
            activated = self.sieve_client.set_merged_filters(filters_config)
            
            return {
                'success': True,
                'message': 'Filters pushed to Sieve server',
                'activated': True,
                'skipped_sections': []
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to push filters: {str(e)}',
                'activated': False,
                'skipped_sections': []
            }
    
    def _validate_rules(self, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate filter rules."""
        errors = []
        
        # Check op is valid
        if 'op' not in rules:
            errors.append({
                'field': 'op',
                'message': 'Rule group must have an operator (op)',
                'severity': 'error'
            })
            return errors
        
        if rules['op'] not in ['and', 'or', 'not']:
            errors.append({
                'field': 'op',
                'message': f"Invalid operator: {rules['op']}",
                'severity': 'error'
            })
        
        # Check rules list exists and is not empty
        if 'rules' not in rules:
            errors.append({
                'field': 'rules',
                'message': 'Rule group must have rules',
                'severity': 'error'
            })
            return errors
        
        # Recursively validate nested rules
        for index, rule in enumerate(rules.get('rules', [])):
            if 'field' in rule and 'operator' in rule:
                # Leaf node
                leaf_errors = self._validate_leaf_rule(rule, index)
                errors.extend(leaf_errors)
            else:
                # Group node
                group_errors = self._validate_rules(rule)
                errors.extend(group_errors)
        
        return errors
    
    def _validate_leaf_rule(self, rule: Dict[str, Any], index: int) -> List[Dict[str, Any]]:
        """Validate a single leaf rule."""
        errors = []
        
        # Check required fields
        if 'field' not in rule:
            errors.append({
                'field': f'rules[{index}].field',
                'message': 'Rule must have a field',
                'severity': 'error'
            })
        
        if 'operator' not in rule:
            errors.append({
                'field': f'rules[{index}].operator',
                'message': 'Rule must have an operator',
                'severity': 'error'
            })
        
        # Validate field
        valid_fields = ['from', 'to', 'cc', 'bcc', 'subject', 'body', 'header', 'size', 'date']
        if rule.get('field') not in valid_fields:
            errors.append({
                'field': f'rules[{index}].field',
                'message': f"Invalid field: {rule.get('field')}",
                'severity': 'error'
            })
        
        # Validate operator based on field
        if rule.get('field') in ['from', 'to', 'cc', 'bcc', 'subject', 'body', 'header']:
            valid_ops = ['contains', 'not_contains', 'equals', 'not_equals', 'matches', 'not_matches', 'regex', 'not_regex']
            if rule.get('operator') not in valid_ops:
                errors.append({
                    'field': f'rules[{index}].operator',
                    'message': f"Invalid operator for text field: {rule.get('operator')}",
                    'severity': 'error'
                })
        elif rule.get('field') == 'size':
            valid_ops = ['greater_than', 'less_than']
            if rule.get('operator') != 'contains':  # size_operator is separate
                # This is a special case, handle elsewhere
                pass
        
        # Check custom header if field is header
        if rule.get('field') == 'header' and 'custom_header' not in rule:
            errors.append({
                'field': f'rules[{index}].custom_header',
                'message': 'Custom header name is required when field is "header"',
                'severity': 'error'
            })
        
        return errors


    def _validate_actions(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate filter actions."""
        errors = []
        
        if not actions:
            errors.append({
                'field': 'actions',
                'message': 'At least one action is required',
                'severity': 'error'
            })
            return errors
        
        valid_methods = ['fileinto', 'redirect', 'discard', 'keep', 'stop', 'flag', 'mark', 'add_tag']
        
        for index, action in enumerate(actions):
            if 'method' not in action:
                errors.append({
                    'field': f'actions[{index}].method',
                    'message': 'Action must have a method',
                    'severity': 'error'
                })
                continue
            
            if action['method'] not in valid_methods:
                errors.append({
                    'field': f'actions[{index}].method',
                    'message': f"Invalid action method: {action['method']}",
                    'severity': 'error'
                })
                continue
            
            # Validate method-specific arguments
            if action['method'] == 'fileinto':
                if 'arguments' not in action or 'folders' not in action['arguments']:
                    errors.append({
                        'field': f'actions[{index}].arguments.folders',
                        'message': 'fileinto action requires folders',
                        'severity': 'error'
                    })
        
        return errors
    
    def _compile_to_sieve(self, filter: Filter) -> str:
        """Compile a filter to Sieve script (for validation and preview)."""
        # This is a simplified version - the full implementation would use
        # the existing ClientSieve._add_filter_to_set and related methods
        
        # For validation purposes, we just need to ensure the structure
        # can be converted to Sieve
        
        # Return a mock Sieve script for now
        return f"require [\"fileinto\"];\n\n# Filter: {filter.name}"
```

---

## Implementation Plan

### Phase 1: Backend API (Weeks 1-2)
**Goal**: Complete REST API for filter management

- [ ] **Task 1.1**: Create `ApiFilters.py` with all endpoints
- [ ] **Task 1.2**: Implement `FilterService` with CRUD operations
- [ ] **Task 1.3**: Add database models for filter storage
- [ ] **Task 1.4**: Integrate with existing `ClientSieve.py`
- [ ] **Task 1.5**: Add validation logic
- [ ] **Task 1.6**: Add push-to-Sieve functionality
- [ ] **Task 1.7**: Create comprehensive API tests

**Deliverables:**
- Working REST API for filter management
- Integration with Sieve server
- Database storage for filters
- Unit and integration tests

### Phase 2: Enhanced Frontend (Weeks 3-4)
**Goal**: Build drag-and-drop filter builder

- [ ] **Task 2.1**: Enhance `FilterList` component with reordering
- [ ] **Task 2.2**: Create `RuleBuilder` component with drag-and-drop
- [ ] **Task 2.3**: Create `ActionBuilder` component
- [ ] **Task 2.4**: Implement `FilterPreview` component
- [ ] **Task 2.5**: Add real-time validation
- [ ] **Task 2.6**: Connect to backend API (remove fake API)
- [ ] **Task 2.7**: Add error handling and user feedback
- [ ] **Task 2.8**: Create frontend tests

**Deliverables:**
- Complete visual filter builder
- Real-time validation and preview
- Integration with backend API
- Responsive design

### Phase 3: Advanced Features (Weeks 5-6)
**Goal**: Add polish and advanced functionality

- [ ] **Task 3.1**: Add filter templates
- [ ] **Task 3.2**: Implement auto-save for drafts
- [ ] **Task 3.3**: Add bulk actions
- [ ] **Task 3.4**: Improve preview with actual email matching
- [ ] **Task 3.5**: Add keyboard shortcuts
- [ ] **Task 3.6**: Implement accessibility (WCAG 2.1)
- [ ] **Task 3.7**: Add import/export functionality
- [ ] **Task 3.8**: Performance optimization

**Deliverables:**
- Filter templates library
- Auto-save functionality
- Improved preview
- Accessibility compliance
- Import/export support

### Phase 4: Testing & Polish (Week 6)
**Goal**: Production readiness

- [ ] **Task 4.1**: End-to-end testing
- [ ] **Task 4.2**: Cross-browser testing
- [ ] **Task 4.3**: Mobile responsiveness testing
- [ ] **Task 4.4**: Performance testing
- [ ] **Task 4.5**: Security review
- [ ] **Task 4.6**: Documentation
- [ ] **Task 4.7**: User testing and feedback

**Deliverables:**
- Fully tested filter editor
- Production-ready code
- Complete documentation

---

## Testing

### Test Strategy

| Test Type | Coverage | Tools | Status |
|-----------|----------|-------|--------|
| Backend Unit Tests | 95%+ | pytest | ❌ To Do |
| Backend Integration Tests | All endpoints | pytest + httpx | ❌ To Do |
| Frontend Unit Tests | All components | Jest + React Testing Library | ⚠️ Partial |
| Frontend Integration Tests | User flows | Cypress | ❌ To Do |
| End-to-End Tests | Complete workflows | Cypress | ❌ To Do |
| Manual Testing | All features | Browser + Clients | ❌ To Do |

### Example Tests

**Backend Test (Python):**
```python
# tests/test_api/test_filters.py
import pytest
from app.api.v1.mail.ApiFilters import blp as filters_api
from app.service.FilterService import FilterService

@pytest.fixture
def client(app):
    """Test client with authentication."""
    client = app.test_client()
    # Add auth token
    client.set_cookie('localhost', 'jwt_token', 'test_token')
    yield client

class TestFilterAPI:
    def test_list_filters_empty(self, client):
        """Test listing filters when none exist."""
        response = client.get('/api/v1/mailboxes/0/filters')
        assert response.status_code == 200
        data = response.get_json()
        assert data['error_code'] == 'S000000'
        assert data['data']['filters'] == []
        assert data['data']['total_count'] == 0
    
    def test_create_filter(self, client):
        """Test creating a new filter."""
        filter_data = {
            'name': 'Test Filter',
            'enabled': True,
            'priority': 1,
            'rules': {
                'op': 'and',
                'rules': [
                    {'field': 'subject', 'operator': 'contains', 'value': 'test'}
                ]
            },
            'actions': [
                {'method': 'fileinto', 'arguments': {'folders': ['Test']}}
            ]
        }
        response = client.post('/api/v1/mailboxes/0/filters', json=filter_data)
        assert response.status_code == 201
        data = response.get_json()
        assert data['error_code'] == 'S000000'
        assert data['data']['filter']['name'] == 'Test Filter'
        assert 'id' in data['data']['filter']
    
    def test_validate_filter(self, client):
        """Test filter validation."""
        filter_data = {
            'rules': {
                'op': 'and',
                'rules': [
                    {'field': 'subject', 'operator': 'contains', 'value': 'test'}
                ]
            },
            'actions': [
                {'method': 'discard', 'arguments': {}}
            ]
        }
        response = client.post('/api/v1/mailboxes/0/filters/validate', json=filter_data)
        assert response.status_code == 200
        data = response.get_json()
        assert data['data']['valid'] == True
        assert data['data']['errors'] == []
```

**Frontend Test (TypeScript):**
```typescript
// tests/features/user-settings/mail/filters/rule-builder.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { RuleBuilder } from '@/features/user-settings/mail/filters/components/rule-builder';
import { FilterRuleGroup } from '@/features/user-settings/mail/filters/mail-filters-types';

describe('RuleBuilder', () => {
  const defaultRules: FilterRuleGroup = {
    op: 'and',
    rules: [
      { field: 'subject', operator: 'contains', value: 'test' }
    ]
  };

  it('renders with default rules', () => {
    const onChange = jest.fn();
    render(
      <RuleBuilder
        rules={defaultRules}
        onChange={onChange}
        availableFields={[...]}
        availableOperators={[...]}
      />
    );
    
    expect(screen.getByText('subject')).toBeInTheDocument();
    expect(screen.getByText('contains')).toBeInTheDocument();
    expect(screen.getByDisplayValue('test')).toBeInTheDocument();
  });

  it('calls onChange when rule is modified', () => {
    const onChange = jest.fn();
    render(
      <RuleBuilder
        rules={defaultRules}
        onChange={onChange}
        availableFields={[...]}
        availableOperators={[...]}
      />
    );
    
    const valueInput = screen.getByDisplayValue('test');
    fireEvent.change(valueInput, { target: { value: 'updated' } });
    
    expect(onChange).toHaveBeenCalled();
  });
});
```

---

## Configuration

### Environment Variables

```bash
# Filter Settings
SOGO_FILTER_MAX_PER_ACCOUNT=100
SOGO_FILTER_ENABLE_AUTO_SAVE=true
SOGO_FILTER_AUTO_SAVE_INTERVAL=30  # seconds
SOGO_FILTER_PREVIEW_LIMIT=50  # max emails to show in preview
SOGO_FILTER DržVA_SAVE_ENABLED=true  # Save filters to Sieve automatically
```

### Feature Flags

```python
# In settings.py
FILTER_FEATURES = {
    "drag_drop_builder": True,
    "preview": True,
    "templates": True,
    "auto_save": True,
    "import_export": True,
    "sharing": False,  # Future feature
}
```

---

## Deployment

### Migration Steps

1. **Database Migration:**
   ```bash
   # Add filter tables to database
   flask db migrate -m "Add email filter tables"
   flask db upgrade
   ```

2. **API Configuration:**
   ```python
   # In app/api/v1/__init__.py
   from .mail import ApiFilters
   api.register_blueprint(ApiFilters.blp)
   ```

3. **Nginx Configuration:**
   ```nginx
   # Ensure proper handling of JSON requests
   location /api/v1/mailboxes/ {
       proxy_pass http://sogo6-server:5000;
       proxy_set_header Content-Type "application/json";
       proxy_set_header X-Content-Type-Options "nosniff";
   }
   ```

4. **Feature Rollout:**
   ```bash
   # Enable gradually
   export SOGO_FILTER_FEATURE_FLAG=true
   
   # Monitor for issues
   docker-compose logs -f | grep filter
   ```

---

## Success Criteria

- [ ] **Functional**: All API endpoints work correctly
- [ ] **User-Friendly**: Intuitive drag-and-drop interface
- [ ] **Compatible**: Works with all Sieve-capable mail servers
- [ ] **Performant**: Fast validation and preview (sub-second)
- [ ] **Reliable**: No data loss, handles edge cases
- [ ] **Accessible**: WCAG 2.1 AA compliant
- [ ] **Secure**: Input validation, proper error handling
- [ ] **Tested**: >90% test coverage
- [ ] **Documented**: Complete API and user documentation

---

## References

### Existing Code
- [ClientSieve.py](../app/manager/mail/ClientSieve.py) - Sieve client implementation
- [filter.py](../app/api/v1/mail/schemas/filter.py) - Filter schemas
- [Filters Feature](https://github.com/tobias-weiss-ai-xr/SOGo6-dockerized/tree/main/sogo6-ui/src/features/user-settings/mail/filters) - Frontend implementation

### RFCs
- [RFC 5228 - Sieve](https://tools.ietf.org/html/rfc5228) - Sieve base specification
- [RFC 5231 - Sieve Extensions](https://tools.ietf.org/html/rfc5231) - List of Sieve extensions
- [ManageSieve Protocol](https://wiki.dovecot.org/Pigeonhole/Sieve/ManageSieve) - Dovecot ManageSieve

### Libraries
- [sievelib](https://github.com/AlexisMega/sievelib) - Python Sieve library (already in use)
- [react-beautiful-dnd](https://github.com/atlassian/react-beautiful-dnd) - Drag and drop for React
- [react-query](https://react-query.tanstack.com/) - Data fetching (already in use)

---

## Appendix

### Field Options

```typescript
// Available fields for filtering
const fieldOptions = [
  { value: 'from', label: 'From', description: 'Sender email address' },
  { value: 'to', label: 'To', description: 'Recipient email address' },
  { value: 'cc', label: 'Cc', description: 'CC recipient' },
  { value: 'bcc', label: 'Bcc', description: 'BCC recipient' },
  { value: 'subject', label: 'Subject', description: 'Email subject' },
  { value: 'body', label: 'Body', description: 'Email body content' },
  { value: 'header', label: 'Custom Header', description: 'Any email header', requiresCustom: true },
  { value: 'size', label: 'Size', description: 'Message size', requiresSizeOperator: true },
  { value: 'date', label: 'Date', description: 'Message date', requiresDate: true },
];

// Operators for each field type
const operatorOptions = {
  text: ['contains', 'not_contains', 'equals', 'not_equals', 'matches', 'not_matches', 'regex', 'not_regex'],
  size: ['greater_than', 'less_than'],
  date: ['before', 'after', 'on', 'between'],
  boolean: ['is', 'is_not'],
};

// Actions with their required arguments
const actionOptions = [
  {
    value: 'fileinto',
    label: 'Move to Folder',
    description: 'Move message to specified folder',
    arguments: [
      { name: 'folders', type: 'folder_picker', required: true, multiple: true },
      { name: 'create_if_no_exist', type: 'boolean', required: false },
      { name: 'keep_copy', type: 'boolean', required: false },
    ]
  },
  {
    value: 'redirect',
    label: 'Forward to',
    description: 'Redirect message to another address',
    arguments: [
      { name: 'addresses', type: 'email', required: true, multiple: true },
    ]
  },
  {
    value: 'discard',
    label: 'Delete',
    description: 'Discard the message',
    arguments: []
  },
  {
    value: 'keep',
    label: 'Keep',
    description: 'Keep the message in inbox',
    arguments: []
  },
  {
    value: 'stop',
    label: 'Stop Processing',
    description: 'Stop processing further filters',
    arguments: []
  },
  {
    value: 'flag',
    label: 'Set Flag',
    description: 'Set or unset message flag',
    arguments: [
      { name: 'flag', type: 'select', required: true, options: ['flagged', 'unflagged'] }
    ]
  },
  {
    value: 'mark',
    label: 'Mark as',
    description: 'Mark message as read or unread',
    arguments: [
      { name: 'mark', type: 'select', required: true, options: ['read', 'unread'] }
    ]
  },
];
```

### Filter Template Examples

```typescript
// Predefined filter templates
const filterTemplates = [
  {
    name: 'Newsletters',
    description: 'Move newsletters to a separate folder',
    rules: {
      op: 'or',
      rules: [
        { field: 'subject', operator: 'contains', value: 'newsletter' },
        { field: 'subject', operator: 'contains', value: 'update' },
        { field: 'from', operator: 'contains', value: 'noreply' },
      ]
    },
    actions: [
      { method: 'fileinto', arguments: { folders: ['Newsletters'], create_if_no_exist: true } }
    ]
  },
  {
    name: 'Large Attachments',
    description: 'Flag emails with large attachments',
    rules: {
      op: 'and',
      rules: [
        { field: 'size', operator: 'greater_than', value: '5000000' },
      ]
    },
    actions: [
      { method: 'flag', arguments: { flag: 'flagged' } },
      { method: 'add_tag', arguments: { tags: ['large-attachment'] } }
    ]
  },
  {
    name: 'Work Emails',
    description: 'Organize work-related emails',
    rules: {
      op: 'or',
      rules: [
        { field: 'from', operator: 'contains', value: '@company.com' },
        { field: 'to', operator: 'contains', value: '@company.com' },
      ]
    },
    actions: [
      { method: 'fileinto', arguments: { folders: ['Work'] } },
      { method: 'mark', arguments: { mark: 'read' } }
    ]
  },
];
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
**Estimated Total Effort**: 4-6 weeks  
**Prerequisites**: Existing Sieve backend (✅ Complete), Frontend filter components (📋 In Progress)
