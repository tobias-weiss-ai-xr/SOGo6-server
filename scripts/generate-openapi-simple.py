#!/usr/bin/env python3
"""
Simple OpenAPI generator that documents the SOGo6 API based on directory structure.
This creates a comprehensive spec without needing to import the Flask app.
"""

import json
import sys
from pathlib import Path


def generate_openapi_spec():
    """Generate OpenAPI specification based on known API structure."""
    
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "SOGo6 Groupware Server API",
            "version": "6.0.0-alpha1",
            "description": "SOGo6 is a modern groupware server providing email, calendar, contacts, tasks, and collaboration features. This REST API allows clients to interact with all SOGo6 functionality.",
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
            {"url": "https://api.sogo.example.com/api/v1", "description": "Production"},
            {"url": "http://localhost:5000/api/v1", "description": "Development"},
            {"url": "/api/v1", "description": "Relative path"}
        ],
        "paths": {},
        "components": {
            "schemas": {},
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "JWT token from /api/user/v1/auth/login"
                }
            },
            "responses": {
                "NotFound": {
                    "description": "Resource not found",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                },
                "Unauthorized": {
                    "description": "Authentication required",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                },
                "Forbidden": {
                    "description": "Insufficient permissions",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                },
                "RateLimited": {
                    "description": "Too many requests",
                    "headers": {"X-RateLimit-Retry-After": {"schema": {"type": "integer"}}}
                }
            }
        },
        "security": [{"bearerAuth": []}],
        "tags": [
            {"name": "system", "description": "System information and configuration"},
            {"name": "auth", "description": "Authentication and session management"},
            {"name": "admin", "description": "Administrative operations"},
            {"name": "mail", "description": "Email operations"},
            {"name": "calendar", "description": "Calendar and event operations"},
            {"name": "contact", "description": "Address book operations"},
            {"name": "user", "description": "User profile and settings"},
            {"name": "health", "description": "Health checking"}
        ]
    }
    
    # Add common schemas
    spec["components"]["schemas"] = {
        "Error": {
            "type": "object",
            "properties": {
                "error_code": {"type": "string", "example": "S000000"},
                "error_msg": {"type": "string", "example": "No Error"},
                "data": {"type": "object", "nullable": True}
            },
            "required": ["error_code", "error_msg"]
        },
        "Success": {
            "type": "object",
            "properties": {
                "data": {"type": "object"},
                "error_code": {"type": "string", "example": "S000000"},
                "error_msg": {"type": "string", "example": "No Error"}
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
        }
    }
    
    # Define all API endpoints based on directory structure
    # Format: /api/{user|admin}/v1/{module}/{resource}
    
    # ========== SYSTEM API ==========
    system_endpoints = [
        ("GET", "/api/v1/system", "Get system parameters", "system"),
        ("GET", "/api/v1/system/ping", "Health check pong", "system"),
    ]
    
    # ========== AUTH API ==========
    auth_endpoints = [
        ("GET", "/api/user/v1/auth/mode", "Get authentication mode for user", "auth"),
        ("POST", "/api/user/v1/auth/login", "Login with username/password", "auth"),
        ("POST", "/api/user/v1/auth/logout", "Logout and invalidate session", "auth"),
        ("GET", "/api/user/v1/auth/callback/<domain>", "SSO callback (OIDC/SAML2)", "auth"),
        ("POST", "/api/user/v1/auth/callback/<domain>", "SSO callback POST (SAML2)", "auth"),
        ("POST", "/api/user/v1/auth/webauthn/registration/start", "Start WebAuthn registration", "auth"),
        ("POST", "/api/user/v1/auth/webauthn/registration/finish", "Finish WebAuthn registration", "auth"),
        ("POST", "/api/user/v1/auth/webauthn/authentication/start", "Start WebAuthn authentication", "auth"),
        ("POST", "/api/user/v1/auth/webauthn/authentication/finish", "Finish WebAuthn authentication", "auth"),
        ("GET", "/api/user/v1/auth/saml2/metadata", "SAML2 metadata XML", "auth"),
        ("GET", "/api/user/v1/auth/saml2/start", "Start SAML2 login", "auth"),
        ("POST", "/api/user/v1/auth/saml2/acs", "SAML2 Assertion Consumer Service", "auth"),
    ]
    
    # ========== MAIL API ==========
    mail_endpoints = [
        ("GET", "/api/user/v1/mail/mailboxes", "List all mailboxes", "mail"),
        ("POST", "/api/user/v1/mail/mailboxes", "Create mailbox", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>", "Get mailbox details", "mail"),
        ("PUT", "/api/user/v1/mail/mailboxes/<mailbox_id>", "Update mailbox", "mail"),
        ("DELETE", "/api/user/v1/mail/mailboxes/<mailbox_id>", "Delete mailbox", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages", "List messages in mailbox", "mail"),
        ("POST", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages", "Copy/move messages to mailbox", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>", "Get message details", "mail"),
        ("PUT", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>", "Update message (read/unread, flags)", "mail"),
        ("DELETE", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>", "Delete message", "mail"),
        ("POST", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>/forward", "Forward message", "mail"),
        ("POST", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>/reply", "Reply to message", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>/raw", "Get raw message source", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>/attachments", "List attachments", "mail"),
        ("GET", "/api/user/v1/mail/mailboxes/<mailbox_id>/messages/<message_id>/attachments/<attachment_id>", "Download attachment", "mail"),
        ("POST", "/api/user/v1/mail/messages/send", "Send new email", "mail"),
        ("POST", "/api/user/v1/mail/messages/import", "Import message (EML)", "mail"),
        ("POST", "/api/user/v1/mail/messages/batch", "Batch operations on messages", "mail"),
        ("GET", "/api/user/v1/mail/search", "Search messages", "mail"),
        ("POST", "/api/user/v1/mail/folders/move", "Move folder", "mail"),
        ("GET", "/api/user/v1/mail/folders/subscriptions", "Get subscribed folders", "mail"),
        ("POST", "/api/user/v1/mail/folders/subscribe", "Subscribe to folder", "mail"),
    ]
    
    # ========== CALENDAR API ==========
    calendar_endpoints = [
        ("GET", "/api/user/v1/calendar/calendars", "List calendars", "calendar"),
        ("POST", "/api/user/v1/calendar/calendars", "Create calendar", "calendar"),
        ("GET", "/api/user/v1/calendar/calendars/<calendar_id>", "Get calendar details", "calendar"),
        ("PUT", "/api/user/v1/calendar/calendars/<calendar_id>", "Update calendar", "calendar"),
        ("DELETE", "/api/user/v1/calendar/calendars/<calendar_id>", "Delete calendar", "calendar"),
        ("GET", "/api/user/v1/calendar/calendars/<calendar_id>/events", "List events", "calendar"),
        ("POST", "/api/user/v1/calendar/calendars/<calendar_id>/events", "Create event", "calendar"),
        ("GET", "/api/user/v1/calendar/calendars/<calendar_id>/events/<event_id>", "Get event", "calendar"),
        ("PUT", "/api/user/v1/calendar/calendars/<calendar_id>/events/<event_id>", "Update event", "calendar"),
        ("DELETE", "/api/user/v1/calendar/calendars/<calendar_id>/events/<event_id>", "Delete event", "calendar"),
        ("POST", "/api/user/v1/calendar/calendars/<calendar_id>/events/<event_id>/attendees", "Manage event attendees", "calendar"),
        ("GET", "/api/user/v1/calendar/freebusy", "Get free/busy information", "calendar"),
        ("POST", "/api/user/v1/calendar/appointment-slots", "Create appointment slots", "calendar"),
        ("GET", "/api/user/v1/calendar/appointment-slots", "List appointment slots", "calendar"),
        ("POST", "/api/user/v1/calendar/scheduling-polls", "Create scheduling poll", "calendar"),
    ]
    
    # ========== CONTACT API ==========
    contact_endpoints = [
        ("GET", "/api/user/v1/contacts/addressbooks", "List address books", "contact"),
        ("POST", "/api/user/v1/contacts/addressbooks", "Create address book", "contact"),
        ("GET", "/api/user/v1/contacts/addressbooks/<addressbook_id>", "Get address book", "contact"),
        ("PUT", "/api/user/v1/contacts/addressbooks/<addressbook_id>", "Update address book", "contact"),
        ("DELETE", "/api/user/v1/contacts/addressbooks/<addressbook_id>", "Delete address book", "contact"),
        ("GET", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts", "List contacts", "contact"),
        ("POST", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts", "Create contact", "contact"),
        ("GET", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts/<contact_id>", "Get contact", "contact"),
        ("PUT", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts/<contact_id>", "Update contact", "contact"),
        ("DELETE", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts/<contact_id>", "Delete contact", "contact"),
        ("GET", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts/<contact_id>/photo", "Get contact photo", "contact"),
        ("POST", "/api/user/v1/contacts/addressbooks/<addressbook_id>/contacts/<contact_id>/photo", "Set contact photo", "contact"),
        ("GET", "/api/user/v1/contacts/autocomplete", "Autocomplete contact search", "contact"),
    ]
    
    # ========== USER API ==========
    user_endpoints = [
        ("GET", "/api/user/v1/user/profile", "Get user profile", "user"),
        ("PUT", "/api/user/v1/user/profile", "Update user profile", "user"),
        ("GET", "/api/user/v1/user/preferences", "Get user preferences", "user"),
        ("PUT", "/api/user/v1/user/preferences", "Update user preferences", "user"),
        ("POST", "/api/user/v1/user/password/change", "Change password", "user"),
        ("GET", "/api/user/v1/user/api-tokens", "List API tokens", "user"),
        ("POST", "/api/user/v1/user/api-tokens", "Create API token", "user"),
        ("DELETE", "/api/user/v1/user/api-tokens/<token_id>", "Revoke API token", "user"),
        ("POST", "/api/user/v1/user/pgp/key", "Upload PGP key", "user"),
        ("GET", "/api/user/v1/user/pgp/key", "Get PGP key", "user"),
        ("DELETE", "/api/user/v1/user/pgp/key", "Delete PGP key", "user"),
        ("POST", "/api/user/v1/user/push/subscribe", "Subscribe to push notifications", "user"),
        ("POST", "/api/user/v1/user/push/unsubscribe", "Unsubscribe from push notifications", "user"),
        ("GET", "/api/user/v1/user/push/vapid-public-key", "Get VAPID public key", "user"),
        ("POST", "/api/user/v1/user/oauth/applications", "Create OAuth application", "user"),
        ("GET", "/api/user/v1/user/oauth/applications", "List OAuth applications", "user"),
        ("GET", "/api/user/v1/user/customization", "Get UI customization", "user"),
        ("PUT", "/api/user/v1/user/customization", "Update UI customization", "user"),
    ]
    
    # ========== ADMIN API ==========
    admin_endpoints = [
        ("GET", "/api/admin/v1/admin/users", "List users", "admin"),
        ("POST", "/api/admin/v1/admin/users", "Create user", "admin"),
        ("GET", "/api/admin/v1/admin/users/<user_id>", "Get user details", "admin"),
        ("PUT", "/api/admin/v1/admin/users/<user_id>", "Update user", "admin"),
        ("DELETE", "/api/admin/v1/admin/users/<user_id>", "Delete user", "admin"),
        ("POST", "/api/admin/v1/admin/users/<user_id>/enable", "Enable user", "admin"),
        ("POST", "/api/admin/v1/admin/users/<user_id>/disable", "Disable user", "admin"),
        ("POST", "/api/admin/v1/admin/users/<user_id>/password/reset", "Reset user password", "admin"),
        ("GET", "/api/admin/v1/admin/domains", "List domains", "admin"),
        ("POST", "/api/admin/v1/admin/domains", "Create domain", "admin"),
        ("GET", "/api/admin/v1/admin/domains/<domain_id>", "Get domain details", "admin"),
        ("PUT", "/api/admin/v1/admin/domains/<domain_id>", "Update domain", "admin"),
        ("DELETE", "/api/admin/v1/admin/domains/<domain_id>", "Delete domain", "admin"),
        ("GET", "/api/admin/v1/admin/config", "Get server configuration", "admin"),
        ("PUT", "/api/admin/v1/admin/config", "Update server configuration", "admin"),
        ("GET", "/api/admin/v1/admin/system", "Get system information", "admin"),
        ("GET", "/api/admin/v1/admin/health", "Admin health check", "admin"),
        ("GET", "/api/admin/v1/admin/audit-log", "Get audit log", "admin"),
        ("GET", "/api/admin/v1/admin/statistics", "Get usage statistics", "admin"),
        ("POST", "/api/admin/v1/admin/backup", "Create backup", "admin"),
        ("GET", "/api/admin/v1/admin/backup", "List backups", "admin"),
        ("POST", "/api/admin/v1/admin/migrate", "Run database migration", "admin"),
    ]
    
    # ========== HEALTH API ==========
    health_endpoints = [
        ("GET", "/api/v1/health", "Health check", "health"),
        ("GET", "/api/v1/health/ready", "Readiness check", "health"),
        ("GET", "/api/v1/health/live", "Liveness check", "health"),
    ]
    
    # ========== JOBS API ==========
    jobs_endpoints = [
        ("GET", "/api/user/v1/jobs", "List user jobs", "jobs"),
        ("POST", "/api/user/v1/jobs", "Create job", "jobs"),
        ("GET", "/api/user/v1/jobs/<job_id>", "Get job status", "jobs"),
        ("DELETE", "/api/user/v1/jobs/<job_id>", "Cancel job", "jobs"),
    ]
    
    # Combine all endpoints
    all_endpoints = (
        system_endpoints + auth_endpoints + mail_endpoints +
        calendar_endpoints + contact_endpoints + user_endpoints +
        admin_endpoints + health_endpoints + jobs_endpoints
    )
    
    # Add all endpoints to spec
    for method, path, description, tag in all_endpoints:
        if path not in spec["paths"]:
            spec["paths"][path] = {}
        
        method_lower = method.lower()
        
        # Determine security
        no_auth_paths = ["/api/v1/health", "/api/v1/system/ping", "/api/user/v1/auth/login"]
        if any(path.startswith(p) for p in no_auth_paths):
            security = []
        else:
            security = [{"bearerAuth": []}]
        
        spec["paths"][path][method_lower] = {
            "tags": [tag],
            "summary": description,
            "description": description,
            "operationId": f"{tag}_{method_lower}_{path.replace('/', '_').replace('<', '').replace('>', '')}",
            "security": security,
            "responses": {
                "200": {"description": "Success", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Success"}}}},
                "400": {"$ref": "#/components/responses/NotFound"},
                "401": {"$ref": "#/components/responses/Unauthorized"},
                "403": {"$ref": "#/components/responses/Forbidden"},
                "404": {"$ref": "#/components/responses/NotFound"},
                "429": {"$ref": "#/components/responses/RateLimited"},
                "500": {"description": "Internal server error"}
            }
        }
    
    return spec


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate OpenAPI spec for SOGo6 Server")
    parser.add_argument("output", nargs="?", default="openapi.json", help="Output file")
    parser.add_argument("--yaml", action="store_true", help="Output YAML format")
    args = parser.parse_args()
    
    spec = generate_openapi_spec()
    
    if args.yaml:
        try:
            import yaml
            with open(args.output, 'w') as f:
                yaml.dump(spec, f, sort_keys=False, default_flow_style=False)
        except ImportError:
            print("Error: pyyaml not installed. Install with: pip install pyyaml")
            print("Saving as JSON instead.")
            with open(args.output, 'w') as f:
                json.dump(spec, f, indent=2)
    else:
        with open(args.output, 'w') as f:
            json.dump(spec, f, indent=2)
    
    # Print summary
    paths_count = len(spec["paths"])
    endpoints_count = sum(len(p) for p in spec["paths"].values())
    
    print(f"\n✓ OpenAPI spec generated: {args.output}")
    print(f"  Paths: {paths_count}")
    print(f"  Endpoints: {endpoints_count}")
    print(f"  Tags: {len(spec['tags'])}")
    print(f"  Schemas: {len(spec['components']['schemas'])}")
    
    return spec


if __name__ == "__main__":
    spec = main()
