from flask_smorest import Blueprint

from .ApiAdminConfig import blp as admin_config_api_blueprint
from .ApiAdminUser import blp as admin_user_api_blueprint
from .ApiAdminAuth import blp as admin_auth_api_blueprint
from .ApiDnsWizard import blp as admin_dns_wizard_api_blueprint
from .ApiSharedMailbox import blp as admin_shared_mailbox_api_blueprint
from .ApiAdminCalendar import blp as admin_calendar_api_blueprint
from .ApiResourceBooking import blp as admin_resource_booking_api_blueprint

from .ApiAuditLog import blp as audit_log_api
from .ApiDomainBranding import blp as domain_branding_api
from .ApiFileSharing import blp as file_sharing_api
from .ApiHealthDashboard import blp as health_dashboard_api
from .ApiMailboxDebug import blp as mailbox_debug_api
from .ApiUsageQuotas import blp as usage_quotas_api
from .ApiBulkUsers import blp as bulk_users_api
from .ApiWebhooks import blp as webhooks_api
from .ApiBackup import blp as backup_api
from .ApiDbMigration import blp as db_migration_api

admin_apis : list[Blueprint] = [
    audit_log_api,
    domain_branding_api,
    file_sharing_api,
    health_dashboard_api,
    mailbox_debug_api,
    usage_quotas_api,
    bulk_users_api,
    webhooks_api,
    backup_api,
    db_migration_api,
    admin_auth_api_blueprint,
    admin_config_api_blueprint,
    admin_user_api_blueprint,
    admin_dns_wizard_api_blueprint,
    admin_shared_mailbox_api_blueprint,
    admin_calendar_api_blueprint,
    admin_resource_booking_api_blueprint,
]
