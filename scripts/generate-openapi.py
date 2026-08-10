#!/usr/bin/env python3
"""Generate OpenAPI specification from Flask routes"""
import json
import sys
from pathlib import Path

def extract_routes():
    """Extract routes from Flask application"""
    try:
        import sys
        sys.path.insert(0, '.')
        from app import create_app
        app = create_app(sogo_state=0)
        
        openapi = {
            "openapi": "3.0.0",
            "info": {
                "title": "SOGo6 Server API",
                "version": "1.0.0",
                "description": "SOGo6 Groupware Server API - Generated from Flask routes"
            },
            "servers": [
                {
                    "url": "/api/v1",
                    "description": "SOGo6 API v1"
                }
            ],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT"
                    }
                }
            },
            "security": [{"bearerAuth": []}]
        }
        
        # Extract routes
        api_routes = []
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/api/'):
                # Skip static files and internal routes
                if any(skip in rule.rule for skip in ['/static/', '/templates/', '/health']):
                    continue
                    
                methods = [m for m in rule.methods if m not in ['HEAD', 'OPTIONS']]
                
                path = rule.rule
                if path not in openapi["paths"]:
                    openapi["paths"][path] = {}
                
                for method in methods:
                    openapi["paths"][path][method.lower()] = {
                        "summary": f"{method} {rule.endpoint}",
                        "operationId": f"{rule.endpoint}_{method.lower()}",
                        "responses": {
                            "200": {"description": "Successful response"},
                            "401": {"description": "Unauthorized"},
                            "404": {"description": "Not found"},
                            "500": {"description": "Internal server error"}
                        }
                    }
                    
                    # Add security for non-public endpoints
                    if not any(skip in path for skip in ['/auth/', '/public/']):
                        openapi["paths"][path][method.lower()]["security"] = [{"bearerAuth": []}]
                
                api_routes.append(path)
        
        print(f"Extracted {len(api_routes)} API routes", file=sys.stderr)
        
        # Group by module
        modules = {}
        for path in api_routes:
            parts = path.split('/')
            if len(parts) > 3:
                module = parts[3]
                if module not in modules:
                    modules[module] = []
                modules[module].append(path)
        
        print(f"Found {len(modules)} API modules: {', '.join(modules.keys())}", file=sys.stderr)
        
        return openapi
        
    except ImportError as e:
        print(f"Warning: Could not import Flask app: {e}", file=sys.stderr)
        print("Generating placeholder spec...", file=sys.stderr)
        
        # Generate placeholder spec
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "SOGo6 Server API",
                "version": "1.0.0",
                "description": "SOGo6 Groupware Server API - Placeholder (run with Flask app available)"
            },
            "paths": {
                "/api/v1/mail/messages": {
                    "get": {"summary": "List messages"},
                    "post": {"summary": "Send message"}
                },
                "/api/v1/calendar/events": {
                    "get": {"summary": "List events"},
                    "post": {"summary": "Create event"}
                },
                "/api/v1/contacts/contacts": {
                    "get": {"summary": "List contacts"},
                    "post": {"summary": "Create contact"}
                },
                "/api/v1/admin/users": {
                    "get": {"summary": "List users"},
                    "post": {"summary": "Create user"}
                }
            }
        }

def main():
    output_file = "openapi.json"
    if len(sys.argv) > 1:
        output_file = sys.argv[1]
    
    spec = extract_routes()
    
    with open(output_file, 'w') as f:
        json.dump(spec, f, indent=2)
    
    print(f"Generated OpenAPI spec: {output_file}", file=sys.stderr)
    print(f"Total paths: {len(spec.get('paths', {}))}", file=sys.stderr)

if __name__ == "__main__":
    main()
