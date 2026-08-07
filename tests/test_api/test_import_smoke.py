"""Import-time smoke tests for modules that previously failed at runtime.

Several API/module files referenced names without importing them
(``request``, ``os``, ``json``, ``base64``, ``err``, ``EventStatus``,
``SystemSettingsObj``, ...).  Importing every module now must succeed;
a missing import in a module body would make its functions raise NameError
when called (previously only caught by pyflakes, never by the suite).

The second test pins the exact regression set: for each module we know was
broken, the names it uses must be defined/imported in that same file.
"""
from __future__ import annotations

import ast
import builtins
import importlib

import pytest

OPTIONAL_DEP_ROOTS = {  # deps legitimately absent from some environments
    "authlib", "ldap3", "qrcode", "boto3", "azure", "webauthn", "pysaml2",
    "icalendar", "vobject", "PIL", "MySQLdb", "ldap",
}

MODULES = [
    # admin API (had `request`/`os`/`secrets`/`err` NameErrors)
    "app.api.v1.admin.ApiMobileApp",
    "app.api.v1.admin.ApiImportExport",
    "app.api.v1.admin.ApiDonorManagement",
    "app.api.v1.admin.ApiWorkflowBuilder",
    "app.api.v1.admin.ApiMatrixChat",
    "app.api.v1.admin.ApiStudentGroups",
    "app.api.v1.admin.ApiVolunteerScheduling",
    "app.api.v1.admin.ApiWebhooks",
    "app.api.v1.admin.ApiScimProvisioning",
    "app.api.v1.admin.ApiCrmLight",
    # modules (missing imports at runtime)
    "app.module.mail.ModuleFilter",
    "app.module.mail.ModuleMail",
    "app.module.admin.ModuleAdminConfig",
    "app.module.auth.ModuleWebAuthn",
    "app.module.calendar.ModuleResourceBooking",
    # interface/auth
    "app.interface.auth.InterfaceMFA",
    "app.interface.auth.InterfaceAuthSSO",
]

# names that were referenced-but-undefined in the module *before* the fix.
# Each entry: (file, nane) that must be defined/imported in that file.
PINNED_NAMES = {
    "app.api.v1.admin.ApiMobileApp": {"request"},
    "app.api.v1.admin.ApiImportExport": {"request"},
    "app.api.v1.admin.ApiDonorManagement": {"request"},
    "app.api.v1.admin.ApiWorkflowBuilder": {"request"},
    "app.api.v1.admin.ApiMatrixChat": {"request"},
    "app.api.v1.admin.ApiStudentGroups": {"request"},
    "app.api.v1.admin.ApiVolunteerScheduling": {"request"},
    "app.api.v1.admin.ApiWebhooks": {"err"},
    "app.api.v1.admin.ApiScimProvisioning": {"os"},
    "app.api.v1.admin.ApiCrmLight": {"secrets"},
    "app.module.mail.ModuleFilter": {"FILTER_SECTION_FILTERS"},
    "app.module.mail.ModuleMail": {"logger_api"},
    "app.module.admin.ModuleAdminConfig": {"json_module"},
    "app.module.auth.ModuleWebAuthn": {"os", "ORIGIN"},
    "app.module.calendar.ModuleResourceBooking": {"EventStatus"},
    "app.interface.auth.InterfaceMFA": {"base64"},
    "app.interface.auth.InterfaceAuthSSO": {"SystemSettingsObj", "UserSourceSettingsObj"},
}


def test_all_modules_import():
    for mod in MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            missing = (e.name or "").split(".")[0]
            if missing.startswith("app") or missing not in OPTIONAL_DEP_ROOTS:
                raise  # our own bug or unknown dep → fail
            pytest.skip(f"optional dependency missing: {missing}")
        except (AttributeError, ImportError) as e:
            raise AssertionError(f"{mod} failed to import: {e}") from e


def _defined_names(tree) -> set[str]:
    """Names bound in the module: imports, defs, assigns, args, loop/with targets."""
    defined = set(dir(builtins))
    for root in ast.walk(tree):
        if isinstance(root, ast.Import):
            for a in root.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(root, ast.ImportFrom):
            for a in root.names:
                defined.add(a.asname or a.name)
        elif isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(root.name)
        elif isinstance(root, ast.arg):
            defined.add(root.arg)
        elif isinstance(root, ast.Assign):
            for t in root.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(root, (ast.For, ast.AsyncFor)):
            for n in ast.walk(root.target):
                if isinstance(n, ast.Name):
                    defined.add(n.id)
        elif isinstance(root, (ast.With, ast.AsyncWith)):
            for item in root.items:
                if item.optional_vars:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            defined.add(n.id)
        elif isinstance(root, ast.comprehension):
            for n in ast.walk(root.target):
                if isinstance(n, ast.Name):
                    defined.add(n.id)
        elif isinstance(root, ast.ExceptHandler) and root.name:
            defined.add(root.name)
    return defined


def test_pinned_names_are_defined():
    """The names that caused NameErrors must now be bound in each module."""
    for mod, names in PINNED_NAMES.items():
        try:
            path = importlib.import_module(mod).__file__
        except ModuleNotFoundError as e:
            missing = (e.name or "").split(".")[0]
            if missing.startswith("app") or missing not in OPTIONAL_DEP_ROOTS:
                raise
            pytest.skip(f"optional dependency missing: {missing}")
        assert path, f"{mod} has no __file__"
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        defined = _defined_names(tree)
        missing = {n for n in names if n not in defined}
        assert not missing, f"{mod} still missing definitions for: {sorted(missing)}"