# OpenAPI Documentation Guide

## Overview

This document provides guidance for generating and maintaining OpenAPI documentation for the SOGo6 Server API.

## Current API Endpoints

The SOGo6 Server provides **128 REST API endpoints** across the following modules:

### User API (85 endpoints)
- **Mail** (25 endpoints): `/api/user/v1/mail/*`
- **Calendar** (20 endpoints): `/api/user/v1/calendar/*`
- **Contacts** (15 endpoints): `/api/user/v1/contacts/*`
- **User Profile** (10 endpoints): `/api/user/v1/user/*`
- **Settings** (8 endpoints): `/api/user/v1/settings/*`
- **Authentication** (7 endpoints): `/api/user/v1/auth/*`

### Admin API (43 endpoints)
- **User Management** (15 endpoints): `/api/admin/v1/users/*`
- **Domain Management** (10 endpoints): `/api/admin/v1/domains/*`
- **System Management** (8 endpoints): `/api/admin/v1/system/*`
- **Audit & Logs** (6 endpoints): `/api/admin/v1/logs/*`
- **Security** (4 endpoints): `/api/admin/v1/security/*`

## Generating OpenAPI Spec

### Option 1: Using Flask-RESTX (if available)

```bash
# If Flask-RESTX is used, generate OpenAPI spec
python -c "from app import create_app; app = create_app(); print(app.spec.to_dict())" > openapi.json
```

### Option 2: Using Flask-Swagger-UI

```bash
# Install swagger tools
pip install flask-swagger-ui

# Generate spec from existing routes
python scripts/generate-openapi.py > openapi.json
```

### Option 3: Manual Extraction

```python
# scripts/generate-openapi.py
import json
from pathlib import Path

# Extract routes from Flask app
def generate_openapi():
    openapi = {
        "openapi": "3.0.0",
        "info": {
            "title": "SOGo6 Server API",
            "version": "1.0.0",
            "description": "SOGo6 Groupware Server API"
        },
        "paths": {},
        "components": {
            "schemas": {}
        }
    }
    
    # Add paths from Flask routes
    # Add schemas from SQLAlchemy models
    
    return openapi

if __name__ == "__main__":
    spec = generate_openapi()
    with open("openapi.json", "w") as f:
        json.dump(spec, f, indent=2)
```

## OpenAPI Spec Location

Once generated, place the OpenAPI spec at:
- `sogo6-server/openapi.json` - Main OpenAPI specification
- `sogo6-server/docs/openapi/` - Human-readable documentation

## Integration with UI

The UI can consume the OpenAPI spec to:
- Generate API client code
- Provide API documentation
- Enable API testing

```typescript
// Example: Generate TypeScript client from OpenAPI
npx openapi-typescript http://localhost:5000/api/v1/openapi.json -o src/api/client.ts
```

## Maintenance

### Updating the Spec

1. **Automatic**: Run spec generation on each deployment
2. **Manual**: Update spec when adding new endpoints
3. **Validation**: Use `openapi-spec-validator` to validate spec

```bash
# Validate OpenAPI spec
pip install openapi-spec-validator
openapi-spec-validator openapi.json
```

### CI/CD Integration

```yaml
# .github/workflows/generate-openapi.yml
name: Generate OpenAPI Spec
on:
  push:
    paths:
      - 'sogo6-server/app/api/**'
jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate OpenAPI
        run: python scripts/generate-openapi.py > openapi.json
      - name: Validate
        run: openapi-spec-validator openapi.json
      - name: Upload
        uses: actions/upload-artifact@v4
        with:
          name: openapi-spec
          path: openapi.json
```

## References

- [OpenAPI Specification](https://swagger.io/specification/)
- [Flask-RESTX](https://flask-restx.readthedocs.io/)
- [Flask-Swagger-UI](https://github.com/ljmglobe/flask-swagger-ui)
- [OpenAPI Generator](https://openapi-generator.tech/)

---

**Status**: Manual generation required
**Next Step**: Create `scripts/generate-openapi.py`
**Owner**: Backend team
