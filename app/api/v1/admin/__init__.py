from flask_smorest import Blueprint

from .ApiAdminConfig import blp as admin_config_api_blueprint
from .ApiAdminUser import blp as admin_user_api_blueprint
from .ApiAdminAuth import blp as admin_auth_api_blueprint
from .ApiDnsWizard import blp as admin_dns_wizard_api_blueprint
from .ApiEmailAuth import blp as admin_email_auth_api_blueprint
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
from .ApiMigration import blp as migration_api
from .ApiConfigAsCode import blp as config_as_code_api
from .ApiApprovalWorkflows import blp as approval_workflows_api
from .ApiHelpdesk import blp as helpdesk_api
from .ApiCrmLight import blp as crm_light_api
from .ApiWorkflowBuilder import blp as workflow_builder_api
from .ApiQuickActions import blp as quick_actions_api

# Tier 6 — Vertical Markets
from .ApiScimProvisioning import blp as scim_provisioning_api
from .ApiStudentGroups import blp as student_groups_api
from .ApiHipaaCompliance import blp as hipaa_compliance_api
from .ApiEidasSignatures import blp as eidas_signatures_api
from .ApiDonorManagement import blp as donor_management_api
from .ApiVolunteerScheduling import blp as volunteer_scheduling_api

# Tier 7 — Advanced
from .ApiImportExport import blp as import_export_api
from .ApiMatrixChat import blp as matrix_chat_api
from .ApiJmapProtocol import blp as jmap_protocol_api
from .ApiActiveSync import blp as active_sync_api
from .ApiMobileApp import blp as mobile_app_api
from .ApiSaml2Admin import blp as saml2_admin_api

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
    migration_api,
    config_as_code_api,
    approval_workflows_api,
    helpdesk_api,
    crm_light_api,
    workflow_builder_api,
    quick_actions_api,
    admin_auth_api_blueprint,
    admin_config_api_blueprint,
    admin_user_api_blueprint,
    admin_dns_wizard_api_blueprint,
    admin_email_auth_api_blueprint,
    admin_shared_mailbox_api_blueprint,
    admin_calendar_api_blueprint,
    admin_resource_booking_api_blueprint,

    # Tier 6
    scim_provisioning_api,
    student_groups_api,
    hipaa_compliance_api,
    eidas_signatures_api,
    donor_management_api,
    volunteer_scheduling_api,

    # Tier 7
    import_export_api,
    matrix_chat_api,
    jmap_protocol_api,
    active_sync_api,
    mobile_app_api,
    saml2_admin_api,
]
