from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    DIRECTION = "direction"
    FACULTY = "faculty"


class Permission(StrEnum):
    MANAGE_USERS = "manage_users"
    IMPORT_EXCEL = "import_excel"
    SYNC_PORTAL_API = "sync_portal_api"
    SYNC_PORTAL_API_FORCE_NOCACHE = "sync_portal_api_force_nocache"
    VIEW_INSTITUTIONAL_PUBLICATIONS = "view_institutional_publications"
    VIEW_GLOBAL_INDICATORS = "view_global_indicators"
    VIEW_ALL_RESEARCHERS_INTERNAL = "view_all_researchers_internal"
    VIEW_OWN_RESEARCHER_DATA = "view_own_researcher_data"
    GENERATE_PDF_REPORT = "generate_pdf_report"
    GENERATE_EXCEL_REPORT = "generate_excel_report"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_SENSITIVE_FIELDS = "view_sensitive_fields"


ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(Permission),
    UserRole.DIRECTION: frozenset(
        {
            Permission.VIEW_INSTITUTIONAL_PUBLICATIONS,
            Permission.VIEW_GLOBAL_INDICATORS,
            Permission.VIEW_ALL_RESEARCHERS_INTERNAL,
            Permission.VIEW_OWN_RESEARCHER_DATA,
            Permission.GENERATE_PDF_REPORT,
            Permission.GENERATE_EXCEL_REPORT,
            Permission.VIEW_AUDIT_LOGS,
            Permission.VIEW_SENSITIVE_FIELDS,
        }
    ),
    UserRole.FACULTY: frozenset(
        {
            Permission.VIEW_INSTITUTIONAL_PUBLICATIONS,
            Permission.VIEW_GLOBAL_INDICATORS,
            Permission.VIEW_OWN_RESEARCHER_DATA,
            Permission.GENERATE_PDF_REPORT,
            Permission.GENERATE_EXCEL_REPORT,
        }
    ),
}


def has_permission(role: str | UserRole, permission: Permission) -> bool:
    try:
        resolved_role = UserRole(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[resolved_role]


def can_view_sensitive_fields(role: str | UserRole) -> bool:
    return has_permission(role, Permission.VIEW_SENSITIVE_FIELDS)


def can_view_all_researchers(role: str | UserRole) -> bool:
    return has_permission(role, Permission.VIEW_ALL_RESEARCHERS_INTERNAL)
