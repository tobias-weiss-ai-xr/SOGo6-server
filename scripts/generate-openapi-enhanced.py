#!/usr/bin/env python3
"""
Enhanced OpenAPI specification generator for SOGo6 Server API.

This script generates a comprehensive OpenAPI 3.0 specification by:
1. Scanning Flask Blueprint files for route definitions
2. Extracting Marshmallow schema information
3. Documenting all API endpoints with proper descriptions
4. Including security schemes and examples

Usage:
    python scripts/generate-openapi-enhanced.py [output.json]
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict


class OpenAPIGenerator:
    """Generates OpenAPI spec from Flask source code."""
    
    def __init__(self, api_dir: Path = Path("app/api")):
        self.api_dir = api_dir
        self.spec: Dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "title": "SOGo6 Groupware Server API",
                "version": "6.0.0-alpha1",
                "description": "SOGo6 is a modern groupware server providing email, calendar, contacts, and collaboration features. This API allows clients to interact with all SOGo6 functionality.",
                "contact": {
                    "name": "SOGo6 Team",
                    "url": "https://github.com/Alinto/sogo6",
                    "email": "sogo@alinto.com"
                },
                "license": {
                    "name": "GNU General Public License v3.0 or later",
                    "url": "https://www.gnu.org/licenses/gpl-3.0.html"
                }
            },
            "servers": [
                {
                    "url": "https://api.sogo.example.com/api/v1",
                    "description": "Production server"
                },
                {
                    "url": "http://localhost:5000/api/v1",
                    "description": "Development server"
                },
                {
                    "url": "/api/v1",
                    "description": "Relative path (for proxy configurations)"
                }
            ],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                        "description": "JWT token obtained from /api/user/v1/auth/login or SSO callback"
                    },
                    "sessionCookie": {
                        "type": "apiKey",
                        "in": "cookie",
                        "name": "session",
                        "description": "Session cookie for browser-based authentication"
                    }
                }
            },
            "security": [{"bearerAuth": []}],
            "tags": [],
            "externalDocs": {
                "description": "SOGo6 Documentation",
                "url": "https://docs.sogo.example.com"
            }
        }
        self.module_docs = self._load_module_documentation()
    
    def _load_module_documentation(self) -> Dict[str, str]:
        """Load documentation for each API module."""
        return {
            "system": "System information and health checks",
            "auth": "Authentication endpoints (login, logout, SSO)",
            "admin": "Administrative API for managing users, domains, and settings",
            "mail": "Email functionality (folders, messages, sending)",
            "calendar": "Calendar and event management",
            "contact": "Address book and contact management",
            "user": "User profile and preferences",
            "health": "Health monitoring and diagnostics",
            "jobs": "Background job management"
        }
    
    def _get_module_name(self, path: Path) -> str:
        """Extract module name from file path."""
        parts = path.relative_to(self.api_dir).parts
        if parts and parts[0] == "v1":
            if len(parts) > 1:
                return parts[1]
        return "unknown"
    
    def _extract_routes_from_file(self, filepath: Path) -> List[Dict[str, Any]]:
        """Extract Flask route definitions from a Python file."""
        routes = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
            return routes
        
        # Pattern 1: @blp.route("/path") class ClassName
        # Pattern 2: @blp.route("/path") def function_name
        # Pattern 3: @blp.before_request (skip)
        # Pattern 4: Multiple methods in route decorator
        
        # Find all route decorators
        route_pattern = r'@(?:blp|app)\.(?:route|before_request|after_request)\([^)]*\)'
        
        # More specific: look for @blp.route("/...")
        route_blocks = re.finditer(
            r'@(blp|app)\.(route)\([^)]*([^\)]*)\)\s*(?:class|def)\s+(\w+)',
            content,
            re.MULTILINE
        )
        
        for match in route_blocks:
            blp_name, _, route_arg, class_name = match.groups()
            
            # Extract route path
            # Could be: @blp.route("/path") or @blp.route("/path", methods=[...])
            path_match = re.search(r'"([^"]+)"', route_arg)
            if path_match:
                path = path_match.group(1)
            else:
                path_match = re.search(r"'([^']+)'", route_arg)
                if path_match:
                    path = path_match.group(1)
                else:
                    continue
            
            # Extract methods
            methods_match = re.search(r'methods=\[([^\]]+)\]', route_arg)
            if methods_match:
                methods_str = methods_match.group(1)
                methods = [m.strip().strip('"').strip("'") for m in methods_str.split(',')]
            else:
                # Default methods based on HTTP verbs in the class
                methods = self._infer_methods_from_class(content, class_name, match.start())
            
            if not methods:
                methods = ["GET"]  # Default
            
            # Clean up methods
            methods = [m for m in methods if m in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]]
            if not methods:
                methods = ["GET"]
            
            # Get docstring for description
            description = self._extract_docstring(content, class_name, match.start())
            
            routes.append({
                "path": path,
                "methods": methods,
                "class": class_name,
                "description": description,
                "module": self._get_module_name(filepath)
            })
        
        return routes
    
    def _infer_methods_from_class(self, content: str, class_name: str, start_pos: int) -> List[str]:
        """Infer HTTP methods from class method definitions."""
        methods = []
        
        # Find the class definition
        class_pattern = rf'class\s+{class_name}\s*[:(]'
        class_match = re.search(class_pattern, content[start_pos:])
        
        if class_match:
            # Find all method definitions within the class
            # Look for def get(self), def post(self), etc.
            class_start = start_pos + class_match.start()
            
            # Find the end of the class (next class or end of file)
            next_class = re.search(r'\nclass\s+\w+', content[class_start+10:])
            if next_class:
                class_end = class_start + 10 + next_class.start()
            else:
                class_end = len(content)
            
            class_content = content[class_start:class_end]
            
            # Find HTTP method methods
            for method in ["get", "post", "put", "delete", "patch"]:
                if re.search(rf'def\s+{method}\s*\(', class_content):
                    methods.append(method.upper())
            
            if not methods:
                # Check for all HTTP methods
                for method in ["get", "post", "put", "delete", "patch"]:
                    if re.search(rf'\s+{method}\s*=', class_content):
                        methods.append(method.upper())
        
        return methods
    
    def _extract_docstring(self, content: str, class_name: str, start_pos: int) -> str:
        """Extract docstring from class or function."""
        # Find the class/function definition
        pattern = rf'(?:class|def)\s+{class_name}\s*[(\[]'
        match = re.search(pattern, content[start_pos:])
        
        if match:
            pos = start_pos + match.end()
            # Find the opening quote of the docstring
            docstring_match = re.search(r'["\']{3}', content[pos:])
            if docstring_match:
                quote_type = docstring_match.group(0)
                doc_start = pos + docstring_match.start() + len(quote_type)
                # Find the closing quote
                doc_end_match = re.search(quote_type, content[doc_start:])
                if doc_end_match:
                    doc_content = content[doc_start:doc_start + doc_end_match.start()]
                    # Clean up whitespace
                    return re.sub(r'\s+', ' ', doc_content).strip()
        
        return ""
    
    def scan_api_directory(self) -> Dict[str, List[Dict[str, Any]]]:
        """Scan the API directory for route files."""
        modules = defaultdict(list)
        
        for py_file in self.api_dir.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            if "schema" in py_file.parts or "schemas" in py_file.parts:
                continue
            
            routes = self._extract_routes_from_file(py_file)
            for route in routes:
                modules[route["module"]].append(route)
        
        return dict(modules)
    
    def _add_common_parameters(self, spec: Dict[str, Any]) -> None:
        """Add common parameters to the spec."""
        spec["components"]["parameters"] = {
            "X-Request-ID": {
                "name": "X-Request-ID",
                "in": "header",
                "description": "Unique request identifier for tracing",
                "required": False,
                "schema": {"type": "string", "format": "uuid"}
            },
            "Accept-Language": {
                "name": "Accept-Language",
                "in": "header",
                "description": "Preferred language for responses",
                "required": False,
                "schema": {"type": "string", "default": "en-US"}
            }
        }
    
    def _add_common_schemas(self, spec: Dict[str, Any]) -> None:
        """Add common schemas to the spec."""
        schemas = {
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "error_code": {"type": "string", "description": "Machine-readable error code"},
                    "error_msg": {"type": "string", "description": "Human-readable error message"},
                    "data": {"type": "object", "nullable": True, "description": "Additional error data"}
                },
                "required": ["error_code", "error_msg"]
            },
            "SuccessResponse": {
                "type": "object",
                "properties": {
                    "data": {"type": "object", "description": "Response data"},
                    "error_code": {"type": "string", "enum": ["S000000"], "description": "Success code"},
                    "error_msg": {"type": "string", "enum": ["No Error"], "description": "Success message"}
                }
            },
            "Pagination": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "minimum": 1, "default": 1},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "total": {"type": "integer"},
                    "total_pages": {"type": "integer"}
                }
            },
            "FilterParams": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "description": "Filter expression"},
                    "sort": {"type": "string", "description": "Sort field"},
                    "order": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}
                }
            }
        }
        spec["components"]["schemas"].update(schemas)
    
    def _add_common_responses(self, spec: Dict[str, Any]) -> None:
        """Add common responses to the spec."""
        spec["components"]["responses"] = {
            "NotFound": {
                "description": "Resource not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                }
            },
            "Unauthorized": {
                "description": "Authentication required or token expired",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                }
            },
            "Forbidden": {
                "description": "Insufficient permissions",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                }
            },
            "RateLimited": {
                "description": "Too many requests",
                "headers": {
                    "X-RateLimit-Retry-After": {
                        "description": "Seconds until rate limit resets",
                        "schema": {"type": "integer"}
                    }
                }
            },
            "InternalError": {
                "description": "Internal server error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                }
            }
        }
    
    def _add_module_tags(self, modules: Dict[str, List]) -> None:
        """Add tags for each module."""
        for module_name, description in self.module_docs.items():
            if module_name not in ["unknown"]:
                tag = {
                    "name": module_name,
                    "description": description
                }
                if tag not in self.spec["tags"]:
                    self.spec["tags"].append(tag)
        
        # Sort tags alphabetically
        self.spec["tags"].sort(key=lambda x: x["name"])
    
    def generate_spec(self) -> Dict[str, Any]:
        """Generate the complete OpenAPI specification."""
        print("Scanning API directory...")
        modules = self.scan_api_directory()
        
        print(f"Found {len(modules)} modules: {', '.join(modules.keys())}")
        
        # Add common definitions
        self._add_common_parameters(self.spec)
        self._add_common_schemas(self.spec)
        self._add_common_responses(self.spec)
        self._add_module_tags(modules)
        
        # Process each module
        total_routes = 0
        for module_name, routes in modules.items():
            print(f"  Processing module: {module_name} ({len(routes)} routes)")
            
            for route in routes:
                path = route["path"]
                methods = route["methods"]
                
                # Build full path (ensure it's under /api/v1/)
                if not path.startswith("/api/"):
                    # This is a blueprint-relative path
                    if module_name == "admin":
                        full_path = f"/api/admin/v1{path}"
                    else:
                        full_path = f"/api/user/v1{path}"
                else:
                    full_path = path
                
                # Initialize path in spec
                if full_path not in self.spec["paths"]:
                    self.spec["paths"][full_path] = {}
                
                # Add each method
                for method in methods:
                    method_lower = method.lower()
                    
                    operation = {
                        "tags": [module_name],
                        "summary": route.get("class", "Unknown"),
                        "description": route.get("description", ""),
                        "operationId": f"{module_name}_{route.get('class', 'unknown')}_{method_lower}",
                        "responses": {
                            "200": {
                                "description": "Successful response",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/SuccessResponse"}
                                    }
                                }
                            },
                            "400": {"$ref": "#/components/responses/NotFound"},
                            "401": {"$ref": "#/components/responses/Unauthorized"},
                            "403": {"$ref": "#/components/responses/Forbidden"},
                            "404": {"$ref": "#/components/responses/NotFound"},
                            "429": {"$ref": "#/components/responses/RateLimited"},
                            "500": {"$ref": "#/components/responses/InternalError"}
                        }
                    }
                    
                    # Add security for non-public endpoints
                    if not any(skip in full_path for skip in ["/auth/login", "/auth/logout", "/public/", "/health"]):
                        operation["security"] = [{"bearerAuth": []}]
                    else:
                        operation["security"] = []
                    
                    self.spec["paths"][full_path][method_lower] = operation
                    total_routes += 1
        
        print(f"Total routes documented: {total_routes}")
        
        return self.spec
    
    def save_spec(self, output_path: str, format: str = "json") -> None:
        """Save the specification to a file."""
        if format == "json":
            with open(output_path, 'w') as f:
                json.dump(self.spec, f, indent=2)
        elif format == "yaml":
            # Try to use pyyaml, fall back to simple yaml
            try:
                import yaml
                with open(output_path, 'w') as f:
                    yaml.dump(self.spec, f, sort_keys=False, default_flow_style=False)
            except ImportError:
                print("Warning: pyyaml not installed, saving as JSON instead", file=sys.stderr)
                with open(output_path, 'w') as f:
                    json.dump(self.spec, f, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        print(f"OpenAPI spec saved to: {output_path}")
    
    def get_summary(self) -> str:
        """Get a summary of the generated spec."""
        paths = self.spec.get("paths", {})
        tags = self.spec.get("tags", [])
        schemas = self.spec.get("components", {}).get("schemas", {})
        
        return f"""
OpenAPI Specification Summary
==============================
Title: {self.spec['info']['title']}
Version: {self.spec['info']['version']}

Servers: {len(self.spec['servers'])}
Tags: {len(tags)}
Paths: {len(paths)}
Schemas: {len(schemas)}

Path Breakdown:
""" + "\n".join(f"  {tag['name']}: {sum(1 for p in paths.values() if tag['name'] in [t for op in p.values() for t in op.get('tags', [])])} routes" for tag in tags)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate OpenAPI spec for SOGo6 Server")
    parser.add_argument("output", nargs="?", default="openapi.json", help="Output file path")
    parser.add_argument("--format", choices=["json", "yaml"], default="json", help="Output format")
    args = parser.parse_args()
    
    # Determine API directory
    api_dir = Path("app/api")
    if not api_dir.exists():
        # Try from parent directory
        api_dir = Path(__file__).parent.parent / "app" / "api"
    
    generator = OpenAPIGenerator(api_dir)
    spec = generator.generate_spec()
    generator.save_spec(args.output, args.format)
    
    print("\n" + generator.get_summary())


if __name__ == "__main__":
    main()
