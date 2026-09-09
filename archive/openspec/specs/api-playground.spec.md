# API Playground (Swagger UI) Specification

## 1. Overview

**Feature**: API Playground - Interactive OpenAPI Documentation with Swagger UI  
**Status**: ⚠️ Partially Implemented (Backend: ✅ 80% | Frontend: ❌ | Integration: ❌)  
**Priority**: Tier 0 (Foundation)  
**Effort**: Low (1-2 weeks)  
**Dependencies**:
- OpenAPI schema generation via Flask-Smorest (✅ `generate-openapi.py` exists)
- Swagger UI static files (✅ Template exists)
- Authentication system (✅ Complete)

Provide interactive API documentation with try-it-out functionality using Swagger UI, enabling developers to explore, test, and understand all SOGo 6 REST API endpoints.

---

## 2. Goals

### Primary Goals
- Serve OpenAPI specification at runtime
- Interactive Swagger UI for all API versions
- JWT token obtaining and auto-population
- Try-it-out for all authenticated endpoints
- Per-endpoint documentation with examples
- Schema visualization

### Secondary Goals
- Multi-version API support (User v1, Admin v1)
- Dark mode toggle
- Download OpenAPI as JSON/YAML
- Rate limiting information
- Request/response history
- Operation grouping by module

---

## 3. Current State

### Existing Implementation:

**Backend (`scripts/generate-openapi.py`)**:
- Extracts Flask routes automatically
- Generates OpenAPI 3.0.0 spec
- Supports multipart output (JSON)
- Missing: Runtime serving, full schema extraction

**Frontend (`app/templates/swagger-ui.html`)**:
- Custom-styled Swagger UI template
- Login modal for JWT token obtaining
- Custom topbar with SOGo branding
- Rate limit warning banner
- Auto-populates auth token
- Missing: Try-it-out, multi-version selector, download button

**Botlen Packs:**
- Static Swagger UI files not bundled
- OpenAPI spec not served at runtime
- Schema not embedded in route decorators
- Try-it-out disabled in config

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client (Browser)                             │
├─────────────────────────────────────────────────────────────┤
│  Swagger UI Bundle                                             │
│  ├─ Custom template (swagger-ui.html)                         │
│  ├─ SOGo branding and styling                                  │
│  ├─ Login modal for JWT tokens                                 │
│  ├─ Version selector (User API / Admin API)                   │
│  ├─ Dark mode toggle                                          │
│  ├─ Download button                                           │
│  └─ Request interceptor for auth headers                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Server (Flask)                              │
├─────────────────────────────────────────────────────────────┤
│  Routes:                                                        │
│  ├─ GET /docs                         → Swagger UI (unified)   │
│  ├─ GET /docs/openapi.json            → OpenAPI spec           │
│  ├─ GET /docs/openapi.yaml           → OpenAPI spec (YAML)    │
│  ├─ GET /api/v1/docs                 → Swagger UI (v1 user)   │
│  ├─ GET /api/v1/openapi.json         → v1 OpenAPI spec        │
│  └─ GET /api/admin/v1/docs           → Swagger UI (v1 admin)  │
├─────────────────────────────────────────────────────────────┤
│  OpenAPI Generation:                                            │
│  ├─ Flask-Smorest decorators → Auto-spec extraction           │
│  ├─ Marshmallow schemas → OpenAPI component schemas           │
│  ├─ Manual annotations → Rich descriptions & examples         │
│  └─ Runtime cache → Performance optimization                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Configuration                               │
├─────────────────────────────────────────────────────────────┤
│  Environment Variables:                                         │
│  ├─ SOGO_API_DOCS_ENABLED=true                                  │
│  ├─ SOGO_SWAGGER_UI_URL=/static/swagger-ui                      │
│  ├─ SOGO_OPENAPI_CACHE_ENABLED=true                            │
│  └─ SOGO_OPENAPI_GENERATE_ON_STARTUP=true                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Requirements

### Functional Requirements

| ID | Description | Priority | Status |
|----|-------------|----------|--------|
| FR-001 | Serve OpenAPI spec at `/docs/openapi.json` | P0 | ❌ Not Yet |
| FR-002 | Serve Swagger UI at `/docs` | P0 | ❌ Not Yet |
| FR-003 | Support multiple API versions | P0 | ❌ Not Yet |
| FR-004 | JWT auth token obtaining via UI | P0 | ✅ Done |
| FR-005 | Auto-populate token to Swagger UI | P0 | ✅ Done |
| FR-006 | Enable "Try it out" for all endpoints | P0 | ❌ Not Yet |
| FR-007 | Show rate limit warnings | P1 | ✅ Done |
| FR-008 | Download OpenAPI spec (JSON/YAML) | P1 | ❌ Not Yet |
| FR-009 | Dark mode support | P1 | ❌ Not Yet |
| FR-010 | Group endpoints by module | P1 | ❌ Not Yet |

### Non-Functional Requirements

| ID | Description | Target |
|----|-------------|--------|
| NFR-001 | Page load time | < 2s |
| NFR-002 | Schema generation time | < 500ms |
| NFR-003 | Concurrent users | 50 |
| NFR-004 | Static asset caching | 1 day |

---

## 6. API Endpoints

### Documentation Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/docs` | None | Unified docs page (User + Admin APIs) |
| GET | `/docs/openapi.json` | None | Unified OpenAPI spec (JSON) |
| GET | `/docs/openapi.yaml` | None | Unified OpenAPI spec (YAML) |
| GET | `/api/v1/docs` | User | User API v1 docs |
| GET | `/api/v1/openapi.json` | None | User API v1 spec (JSON) |
| GET | `/api/v1/openapi.yaml` | None | User API v1 spec (YAML) |
| GET | `/api/admin/v1/docs` | Admin | Admin API v1 docs |
| GET | `/api/admin/v1/openapi.json` | None | Admin API v1 spec (JSON) |
| GET | `/api/admin/v1/openapi.yaml` | None | Admin API v1 spec (YAML) |

### Authentication Endpoint (for UI)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/docs/auth/login` | None | Obtain JWT for Swagger UI (proxy) |

---

## 7. Implementation

### Step 1: Enhanced OpenAPI Generation

```python
# sogo6-server/app/service/OpenApiService.py (NEW)

from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from flask import current_app, url_for
from marshmallow import Schema, fields


class OpenApiService:
    """Service for generating and serving OpenAPI specifications."""
    
    # Cache for generated specs
    _spec_cache: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def get_unified_spec(cls) -> Dict[str, Any]:
        """Generate or return cached unified OpenAPI spec."""
        cache_key = 'unified'
        if cache_key in cls._spec_cache:
            return cls._spec_cache[cache_key]
        
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "SOGo6 Server API",
                "version": current_app.config.get('API_VERSION', '1.0.0'),
                "description": cls._generate_description(),
                "contact": {
                    "name": "SOGo6 Team",
                    "email": "support@sogo6.io",
                    "url": "https://sogo6.io"
                },
                "license": {
                    "name": "GPL-2.0-or-later",
                    "url": "https://www.gnu.org/licenses/gpl-2.0.html"
                }
            },
            "servers": [
                {"url": current_app.config.get('API_BASE_URL', '/api'), "description": "SOGo6 API"}
            ],
            "tags": cls._generate_tags(),
            "paths": cls._generate_all_paths(),
            "components": {
                "schemas": cls._generate_schemas(),
                "securitySchemes": cls._generate_security_schemes(),
                "responses": cls._generate_responses()
            },
            "security": [],
            "externalDocs": {
                "url": "https://sogo6.io/docs/api",
                "description": "SOGo6 API Documentation"
            }
        }
        
        cls._spec_cache[cache_key] = spec
        return spec
    
    @classmethod
    def get_user_api_spec(cls) -> Dict[str, Any]:
        """Generate or return cached User API v1 spec."""
        cache_key = 'user_v1'
        if cache_key in cls._spec_cache:
            return cls._spec_cache[cache_key]
        
        spec = cls.get_unified_spec()
        
        # Filter paths to only user API
        filtered_paths = {
            path: methods for path, methods in spec['paths'].items()
            if path.startswith('/api/v1/') and not path.startswith('/api/v1/admin/')
        }
        
        spec = dict(spec)
        spec['paths'] = filtered_paths
        spec['info']['title'] = "SOGo6 User API v1"
        spec['info']['description'] = "SOGo6 User API - For mailbox operations"
        spec['servers'] = [{"url": "/api/v1", "description": "User API v1"}]
        
        # User API uses bearerAuth
        for path_info in spec['paths'].values():
            for method_info in path_info.values():
                # Skip auth endpoints
                if '/auth/' in method_info.get('operationId', ''):
                    continue
                method_info['security'] = [{"bearerAuth": []}]
        
        cls._spec_cache[cache_key] = spec
        return spec
    
    @classmethod
    def get_admin_api_spec(cls) -> Dict[str, Any]:
        """Generate or return cached Admin API v1 spec."""
        cache_key = 'admin_v1'
        if cache_key in cls._spec_cache:
            return cls._spec_cache[cache_key]
        
        spec = cls.get_unified_spec()
        
        # Filter paths to only admin API
        filtered_paths = {
            path: methods for path, methods in spec['paths'].items()
            if path.startswith('/api/admin/v1/')
        }
        
        spec = dict(spec)
        spec['paths'] = filtered_paths
        spec['info']['title'] = "SOGo6 Admin API v1"
        spec['info']['description'] = "SOGo6 Admin API - For system administration"
        spec['servers'] = [{"url": "/api/admin/v1", "description": "Admin API v1"}]
        
        # Admin API uses admin bearer
        for path_info in spec['paths'].values():
            for method_info in path_info.values():
                # Skip auth endpoints
                if '/auth/' in method_info.get('operationId', ''):
                    continue
                method_info['security'] = [{"admin_bearer": []}]
        
        cls._spec_cache[cache_key] = spec
        return spec
    
    @classmethod
    def _generate_description(cls) -> str:
        return f"""# SOGo6 Server API

SOGo6 is a modern, secure groupware server providing email, calendar, contacts,
and collaboration features built on PostgreSQL and OpenLDAP.

## Authentication

SOGo6 has separate authentication realms:

### User API
Use `POST /api/v1/auth/login` to authenticate as a regular user.
Token is valid for user-level operations (mail, calendar, contacts).

### Admin API
Use `POST /api/admin/v1/auth/login` to authenticate as an administrator.
Token is valid for administration operations ONLY.

### WebAuthn/Passkeys
Use `/user/v1/webauthn/*` endpoints for passwordless authentication.

## Rate Limiting
- User API: 20 requests/minute per IP (increase to 100 with auth)
- Admin API: 30 requests/minute per IP (increase to 200 with auth)
- Auth endpoints: 5 requests/minute per IP

## Version
API Version: {current_app.config.get('API_VERSION', '1.0.0')}
"""
    
    @classmethod
    def _generate_tags(cls) -> List[Dict[str, str]]:
        return [
            {"name": "User Authentication", "description": "User authentication endpoints"},
            {"name": "Admin Authentication", "description": "Admin authentication endpoints"},
            {"name": "WebAuthn", "description": "Passwordless authentication with passkeys"},
            {"name": "Mail", "description": "Email and messaging operations"},
            {"name": "Calendar", "description": "Calendar and event operations"},
            {"name": "Contacts", "description": "Address book and contact operations"},
            {"name": "Resources", "description": "Bookable resource operations"},
            {"name": "Admin", "description": "System administration"},
        ]
    
    @classmethod
    def _generate_security_schemes(cls) -> Dict[str, Any]:
        return {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT token from `/api/v1/auth/login` for user operations"
            },
            "admin_bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT token from `/api/admin/v1/auth/login` for admin operations"
            }
        }
    
    @classmethod
    def _generate_responses(cls) -> Dict[str, Any]:
        return {
            "NotFound": {
                "description": "Resource not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            },
            "Unauthorized": {
                "description": "Authentication required",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            },
            "Forbidden": {
                "description": "Access denied",
            },
            "RateLimitExceeded": {
                "description": "Too many requests",
                "headers": {
                    "X-RateLimit-Limit": {"schema": {"type": "integer"}},
                    "X-RateLimit-Remaining": {"schema": {"type": "integer"}},
                    "X-RateLimit-Reset": {"schema": {"type": "integer"}}
                }
            }
        }
    
    @classmethod
    def _generate_all_paths(cls) -> Dict[str, Any]:
        """Extract all paths from Flask app with Flask-Smorest annotations."""
        from flask_smorest import Api
        
        # Get Flask-Smorest API instance
        api: Optional[Api] = None
        for ext in current_app.extensions.values():
            if isinstance(ext, Api):
                api = ext
                break
        
        if not api or not api._spec:
            return {}
        
        # Get spec from Flask-Smorest
        paths = {}
        for path, path_item in api._spec.get('paths', {}).items():
            # Convert path to our format
            paths[path] = {}
            for method, method_spec in path_item.items():
                if method in ['get', 'post', 'put', 'patch', 'delete']:
                    paths[path][method] = dict(method_spec)
        
        return paths
    
    @classmethod
    def _generate_schemas(cls) -> Dict[str, Any]:
        """Extract all Marshmallow schemas."""
        schemas = {}
        
        # Import and convert all schemas
        # This is done by Flask-Smorest automatically
        # We just need to reference them
        
        # Add common schemas
        schemas['Error'] = {
            "type": "object",
            "properties": {
                "error": {"type": "string"},
                "error_msg": {"type": "string"},
                "error_code": {"type": "integer"}
            },
            "required": ["error", "error_msg"]
        }
        
        schemas['Pagination'] = {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1},
                "per_page": {"type": "integer", "minimum": 1, "maximum": 200},
                "total": {"type": "integer"},
                "total_pages": {"type": "integer"}
            }
        }
        
        return schemas
```

### Step 2: Enhanced Swagger UI Template

```html
<!-- sogo6-server/app/templates/swagger-ui.html (COMPLETE) -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title|default('SOGo6 API Documentation') }}</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css">
  <style>
    html { box-sizing: border-box; }
    *, *::before, *::after { box-sizing: inherit; }
    body { margin: 0; background: #fafafa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    
    .topbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: #1a1a2e; color: #fff; }
    .topbar h1 { margin: 0; font-size: 18px; font-weight: 600; }
    .topbar .subtitle { font-size: 13px; opacity: 0.7; margin-left: 12px; }
    .topbar-actions { display: flex; gap: 8px; align-items: center; }
    .btn { padding: 8px 16px; border: 1px solid rgba(255,255,255,0.3); border-radius: 4px; background: transparent; color: #fff; cursor: pointer; font-size: 13px; }
    .btn:hover { background: rgba(255,255,255,0.1); }
    .btn.primary { background: #4a9eff; border-color: #4a9eff; }
    .btn.primary:hover { background: #3a8eef; }
    
    .info-banner { background: #fff3e0; border: 1px solid #ffe0b2; border-radius: 6px; padding: 10px 16px; font-size: 13px; color: #e65100; margin: 16px auto; max-width: 1400px; }
    
    #swagger-ui { max-width: 1400px; margin: 0 auto; padding: 0 20px 40px; }
    
    .login-modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 10000; justify-content: center; align-items: center; }
    .login-modal-overlay.active { display: flex; }
    .login-modal { background: #fff; border-radius: 8px; padding: 24px; width: 400px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
    .login-modal h2 { margin: 0 0 8px; font-size: 18px; }
    .login-modal .desc { color: #666; font-size: 13px; margin-bottom: 16px; }
    .login-modal label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #333; }
    .login-modal input, .login-modal select { width: 100%; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; margin-bottom: 12px; }
    .login-modal .message { font-size: 13px; margin-top: 8px; padding: 8px 12px; border-radius: 4px; display: none; }
    .login-modal .error { background: #fee; border: 1px solid #fcc; color: #c00; }
    .login-modal .success { background: #efe; border: 1px solid #cfc; color: #060; }
    .login-modal .message.visible { display: block; }
    .login-modal .btn-row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
    .theme-toggle { background: none; border: 1px solid rgba(255,255,255,0.3); border-radius: 4px; padding: 6px 10px; cursor: pointer; color: #fff; }
  </style>
</head>
<body>

<div class="topbar">
  <div>
    <h1>{{ title|default('SOGo6 API') }}</h1>
    <span class="subtitle">Interactive API Playground</span>
  </div>
  <div class="topbar-actions">
    <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
    <button class="btn" onclick="downloadOpenApi()">Download JSON</button>
    <button class="btn primary" onclick="showLoginModal()">Get Token</button>
    <button class="btn" onclick="clearAuth()">Clear Token</button>
  </div>
</div>

{% if info_banner %}
<div class="info-banner">{{ info_banner }}</div>
{% else %}
<div class="info-banner">
  <strong>Tip:</strong> Click "Get Token" to authenticate. 
  Rate limits: 20/min (guest), 100/min (authenticated).
</div>
{% endif %}

<div id="swagger-ui"></div>

<!-- Login Modal -->
<div class="login-modal-overlay" id="loginModal">
  <div class="login-modal">
    <h2>Get API Token</h2>
    <p class="desc">Enter credentials to obtain JWT token for API exploration.</p>
    <label for="loginType">Login Type</label>
    <select id="loginType">
      <option value="user">User (mailbox access)</option>
      <option value="admin">Admin (system administration)</option>
    </select>
    <label for="loginUsername">Username or Email</label>
    <input type="text" id="loginUsername" placeholder="user@example.org" autocomplete="username">
    <label for="loginPassword">Password</label>
    <input type="password" id="loginPassword" placeholder="••••••••" autocomplete="current-password">
    <label for="loginMfa">MFA Code <span style="font-weight:400;color:#999;">(optional)</span></label>
    <input type="text" id="loginMfa" placeholder="123456">
    <div class="message error" id="loginError"></div>
    <div class="message success" id="loginSuccess">Token obtained! Use Authorize button below.</div>
    <div class="btn-row">
      <button class="btn" onclick="hideLoginModal()">Cancel</button>
      <button class="btn primary" onclick="doLogin()">Get Token</button>
    </div>
  </div>
</div>

<script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
<script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-standalone-preset.js"></script>
<script>
const ui = SwaggerUIBundle({
  url: "{{ openapi_url }}",
  dom_id: '#swagger-ui',
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
  plugins: [SwaggerUIBundle.plugins.DownloadUrl],
  layout: "StandaloneLayout",
  defaultModelsExpandDepth: 1,
  defaultModelExpandDepth: 1,
  docExpansion: "list",
  filter: true,
  showExtensions: true,
  showCommonExtensions: true,
  tryItOutEnabled: true,
});

function showLoginModal() { document.getElementById('loginModal').classList.add('active'); }
function hideLoginModal() { document.getElementById('loginModal').classList.remove('active'); }
function getLoginEndpoint() { return document.getElementById('loginType').value === 'admin' ? '/api/admin/v1/auth/login' : '/api/v1/auth/login'; }

async function doLogin() {
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const mfa = document.getElementById('loginMfa').value.trim();
  const errorEl = document.getElementById('loginError');
  const successEl = document.getElementById('loginSuccess');
  errorEl.classList.remove('visible'); successEl.classList.remove('visible');
  
  if (!username || !password) { errorEl.textContent = 'Username and password required'; errorEl.classList.add('visible'); return; }
  
  const body = { username, password, ...(mfa && { mfa_code: mfa }) };
  try {
    const resp = await fetch(getLoginEndpoint(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (!resp.ok || !data.data?.token) {
      errorEl.textContent = data.error_msg || 'Login failed';
      errorEl.classList.add('visible');
      return;
    }
    const token = data.data.token;
    const authName = document.getElementById('loginType').value === 'admin' ? 'admin_bearer' : 'bearerAuth';
    ui.authActions.authorize({ [authName]: { name: authName, schema: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' }, value: token } });
    successEl.classList.add('visible');
    setTimeout(hideLoginModal, 1500);
  } catch (err) { errorEl.textContent = 'Network error: ' + err.message; errorEl.classList.add('visible'); }
}

function clearAuth() { ui.authActions.logout(); }
function downloadOpenApi() { window.location.href = "{{ openapi_url }}"; }
function toggleTheme() { document.documentElement.classList.toggle('dark'); }

document.getElementById('loginModal').addEventListener('click', (e) => { if (e.target === e.currentTarget) hideLoginModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && document.getElementById('loginModal').classList.contains('active')) doLogin(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideLoginModal(); });
</script>
</body>
</html>
```

### Step 3: Flask Routes

```python
# sogo6-server/app/api/main.py (or new docs.py)

from flask import Blueprint, render_template, jsonify
from app.service.OpenApiService import OpenApiService

bp = Blueprint('docs', __name__, url_prefix='/docs')


@bp.route('/')
def docs():
    """Serve Swagger UI for all APIs."""
    return render_template(
        'swagger-ui.html',
        title='SOGo6 API Documentation',
        openapi_url='/docs/openapi.json',
        info_banner='<strong>💡</strong> Select User API or Admin API from the dropdown above. Both use separate authentication.'
    )


@bp.route('/openapi.json')
def openapi_json():
    """Serve unified OpenAPI specification."""
    spec = OpenApiService.get_unified_spec()
    return jsonify(spec)


@bp.route('/openapi.yaml')
def openapi_yaml():
    """Serve unified OpenAPI specification as YAML."""
    import yaml
    spec = OpenApiService.get_unified_spec()
    return yaml.dump(spec, default_flow_style=False), 200, {'Content-Type': 'application/yaml'}


# User API docs
from flask import Blueprint as user_bp
user_docs_bp = Blueprint('user_docs', __name__, url_prefix='/api/v1')


@user_docs_bp.route('/docs')
def user_docs():
    """Serve Swagger UI for User API v1."""
    return render_template(
        'swagger-ui.html',
        title='SOGo6 User API v1',
        openapi_url='/api/v1/openapi.json',
        info_banner='<strong>👤 User API</strong> - For mailbox operations. Use user credentials to authenticate.'
    )


@user_docs_bp.route('/openapi.json')
def user_openapi_json():
    """Serve User API v1 OpenAPI specification."""
    spec = OpenApiService.get_user_api_spec()
    return jsonify(spec)


@user_docs_bp.route('/openapi.yaml')
def user_openapi_yaml():
    """Serve User API v1 OpenAPI specification as YAML."""
    import yaml
    spec = OpenApiService.get_user_api_spec()
    return yaml.dump(spec, default_flow_style=False), 200, {'Content-Type': 'application/yaml'}


# Admin API docs
from flask import Blueprint as admin_bp
admin_docs_bp = Blueprint('admin_docs', __name__, url_prefix='/api/admin/v1')


@admin_docs_bp.route('/docs')
def admin_docs():
    """Serve Swagger UI for Admin API v1."""
    return render_template(
        'swagger-ui.html',
        title='SOGo6 Admin API v1',
        openapi_url='/api/admin/v1/openapi.json',
        info_banner='<strong>🛡️ Admin API</strong> - For system administration. Requires admin credentials.'
    )


@admin_docs_bp.route('/openapi.json')
def admin_openapi_json():
    """Serve Admin API v1 OpenAPI specification."""
    spec = OpenApiService.get_admin_api_spec()
    return jsonify(spec)


@admin_docs_bp.route('/openapi.yaml')
def admin_openapi_yaml():
    """Serve Admin API v1 OpenAPI specification as YAML."""
    import yaml
    spec = OpenApiService.get_admin_api_spec()
    return yaml.dump(spec, default_flow_style=False), 200, {'Content-Type': 'application/yaml'}
```

---

## 8. Configuration

### Environment Variables

```bash
# Enable API documentation (default: true)
SOGO_API_DOCS_ENABLED=true

# Swagger UI URL - can be CDN or local
SOGO_SWAGGER_UI_URL=https://unpkg.com/swagger-ui-dist@5.9.0
# Or: SOGO_SWAGGER_UI_URL=/static/swagger-ui

# OpenAPI cache settings
SOGO_OPENAPI_CACHE_ENABLED=true
SOGO_OPENAPI_CACHE_TTL=300  # seconds

# Generate spec on startup
SOGO_OPENAPI_GENERATE_ON_STARTUP=true
```

### Flask Configuration

```python
# sogo6-server/config.py

class Config:
    # API Documentation
    API_DOCS_ENABLED = os.environ.get('SOGO_API_DOCS_ENABLED', 'true').lower() == 'true'
    SWAGGER_UI_URL = os.environ.get('SOGO_SWAGGER_UI_URL', 'https://unpkg.com/swagger-ui-dist@5.9.0')
    OPENAPI_CACHE_ENABLED = os.environ.get('SOGO_OPENAPI_CACHE_ENABLED', 'true').lower() == 'true'
    OPENAPI_CACHE_TTL = int(os.environ.get('SOGO_OPENAPI_CACHE_TTL', '300'))
    OPENAPI_GENERATE_ON_STARTUP = os.environ.get('SOGO_OPENAPI_GENERATE_ON_STARTUP', 'true').lower() == 'true'
    API_VERSION = os.environ.get('SOGO_API_VERSION', '1.0.0')
    API_BASE_URL = os.environ.get('SOGO_API_BASE_URL', '/api')
```

### Setup in Application Factory

```python
# sogo6-server/app/__init__.py (add to create_app)

def create_app(sogo_state):
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # ... existing setup ...
    
    # Register API documentation routes
    if app.config['API_DOCS_ENABLED']:
        from app.api.docs import bp as docs_bp
        from app.api.user.docs import user_docs_bp
        from app.api.admin.docs import admin_docs_bp
        
        app.register_blueprint(docs_bp)
        app.register_blueprint(user_docs_bp)
        app.register_blueprint(admin_docs_bp)
        
        # Pre-generate OpenAPI spec on startup (optional)
        if app.config['OPENAPI_GENERATE_ON_STARTUP']:
            from app.service.OpenApiService import OpenApiService
            OpenApiService.get_unified_spec()  # Warm the cache
```

---

## 9. Static Files Setup

### Option A: Use CDN (Recommended)

No setup needed. Swagger UI files are loaded from a CDN.

```python
# In template
swagger_ui_url = 'https://unpkg.com/swagger-ui-dist@5.9.0'
```

### Option B: Bundle Locally

```bash
# Download Swagger UI
mkdir -p sogo6-server/static/swagger-ui
cd sogo6-server/static/swagger-ui
wget https://github.com/swagger-api/swagger-ui/releases/download/v5.9.0/swagger-ui-dist.zip
unzip swagger-ui-dist.zip
rm swagger-ui-dist.zip
```

Then update config:
```bash
SOGO_SWAGGER_UI_URL=/static/swagger-ui
```

---

## 10. Implementation Plan

### Phase 1: Backend Setup (1-2 days)

1. **Create `OpenApiService.py`**
   - Implement all static methods (`get_unified_spec`, `get_user_api_spec`, `get_admin_api_spec`)
   - Add caching support
   - Add schema extraction helpers

2. **Create Flask routes**
   - `/docs` - Unified docs page
   - `/docs/openapi.{json,yaml}` - Unified spec
   - `/api/v1/docs` - User API docs
   - `/api/v1/openapi.{json,yaml}` - User API spec
   - `/api/admin/v1/docs` - Admin API docs
   - `/api/admin/v1/openapi.{json,yaml}` - Admin API spec

3. **Add configuration**
   - Environment variables
   - Flask config
   - Application factory integration

### Phase 2: Frontend Enhancement (2-3 days)

1. **Update Swagger UI template**
   - Add dark mode toggle
   - Add version selector dropdown
   - Add download button
   - Improve login modal
   - Add Token display

2. **Add theme support**
   - CSS for dark mode
   - Theme persistence in localStorage
   - Auto-detect system preference

3. **Add helper functions**
   - Token management
   - Version switching
   - Download functionality

### Phase 3: Testing & Polish (1-2 days)

1. **Test all browsers**
   - Chrome/Edge
   - Firefox
   - Safari
   - Mobile browsers

2. **Validate OpenAPI spec**
   - Online validator
   - Try-it-out functionality
   - Schema correctness

3. **Performance testing**
   - Schema generation time
   - Page load time
   - Caching behavior

---

## 11. Success Criteria

- [ ] `/docs` serves unified Swagger UI
- [ ] `/docs/openapi.json` serves valid OpenAPI spec
- [ ] User and Admin API version selectors work
- [ ] JWT authentication via UI works
- [ ] Tokens auto-populate to Swagger UI
- [ ] "Try it out" works for all endpoints
- [ ] All endpoints show proper descriptions
- [ ] Schema visualization works
- [ ] Dark mode toggle works
- [ ] Download buttons work
- [ ] Rate limit warnings visible
- [ ] Performance < 2s page load
- [ ] Performance < 500ms spec generation
- [ ] No broken links in docs

---

## 12. References

### Standards
- [OpenAPI 3.0 Specification](https://swagger.io/specification/)
- [Swagger UI Documentation](https://swagger.io/docs/open-source-tools/swagger-ui/)
- [Flask-Smorest Documentation](https://flask-smorest.readthedocs.io/)

### Libraries
- [Flask-Smorest](https://github.com/marshmallow-code/flask-smorest) - OpenAPI + Marshmallow
- [Swagger UI](https://github.com/swagger-api/swagger-ui) - Interactive API docs
- [PyYAML](https://pyyaml.org/) - YAML serialization

### Guides
- [Swagger UI Setup](https://swagger.io/docs/open-source-tools/swagger-ui/usage/installation/)
- [OpenAPI Tips](https://swagger.io/docs/specification/best-practices/)

---

## Appendix A: OpenAPI Structure

```yaml
openapi: "3.0.3"
info:
  title: "SOGo6 Server API"
  version: "1.0.0"
  description: "SOGo6 Groupware Server REST API"

servers:
  - url: "/api/v1"
    description: "User API v1"
  - url: "/api/admin/v1"
    description: "Admin API v1"

paths:
  /api/v1/auth/login:
    post:
      tags: ["User Authentication"]
      summary: "Login as user"
      requestBody:
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/LoginRequest"
      responses:
        "200":
          description: "Login successful"
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/LoginResponse"

components:
  schemas:
    LoginRequest:
      type: object
      properties:
        username:
          type: string
        password:
          type: string
          format: password

    LoginResponse:
      type: object
      properties:
        data:
          type: object
          properties:
            token:
              type: string

  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
```

---

## Appendix B: Error Handling

```python
from flask import jsonify

@bp.errorhandler(404)
def not_found(e):
    return jsonify({
        "error": "not_found",
        "error_msg": "Resource not found",
        "error_code": 404
    }), 404
```

---

**Document Status**: ✅ Complete  
**Author**: Tobias Weiss (@tobias-weiss-ai-xr)  
**Created**: 2025-08-20  
**Last Modified**: 2025-08-20  
**Target Implementation**: Q3 2025
