"""
Password policy validation utilities.

This module provides functions to validate passwords against domain-specific
security policies defined in UserSourceSettings.
"""

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.config.settings.UserSourceSettings import UserSourceSettingsObj


def _get_setting(settings: Any, key: str, default: Any = None) -> Any:
    """
    Safely get a setting value with a default.
    
    :param settings: Settings object
    :param key: Setting key name
    :param default: Default value if setting is None or doesn't exist
    :return: Setting value or default
    """
    value = getattr(settings, key, default)
    return value if value is not None else default


def validate_password_policy(password: str, settings: "UserSourceSettingsObj") -> list[str]:
    """
    Validate a password against the domain's password policy.
    
    :param password: The password to validate
    :type password: str
    :param settings: User source settings containing password policy
    :type settings: UserSourceSettingsObj
    :return: List of error messages (empty if password is valid)
    :rtype: list[str]
    """
    errors = []
    
    # Get policy settings with safe defaults
    pwd_policy = _get_setting(settings, 'US_PWD_POLICY', False)
    pwd_len_min = _get_setting(settings, 'US_PWD_LEN_MIN', 0)
    pwd_len_max = _get_setting(settings, 'US_PWD_LEN_MAX', 0)
    pwd_uppercase_min = _get_setting(settings, 'US_PWD_UPPERCASE_MIN', 0)
    pwd_lowercase_min = _get_setting(settings, 'US_PWD_LOWERCASE_MIN', 0)
    pwd_digits_min = _get_setting(settings, 'US_PWD_DIGITS_MIN', 0)
    pwd_special_min = _get_setting(settings, 'US_PWD_SPECIAL_MIN', 0)
    pwd_special_allowed = _get_setting(settings, 'US_PWD_SPECIAL_ALLOWED', r'%$&*(){}[]!?\/ @#.,:;+=<>-_')
    
    # Only validate if policy is enabled
    if not pwd_policy:
        return errors
    
    # Check minimum length
    if pwd_len_min > 0 and len(password) < pwd_len_min:
        errors.append(f"Password must be at least {pwd_len_min} characters long")
    
    # Check maximum length
    if pwd_len_max > 0 and len(password) > pwd_len_max:
        errors.append(f"Password must be at most {pwd_len_max} characters long")
    
    # Count character types
    uppercase_count = sum(1 for c in password if c.isupper())
    lowercase_count = sum(1 for c in password if c.islower())
    digit_count = sum(1 for c in password if c.isdigit())
    special_count = sum(1 for c in password if not c.isalnum())
    
    # Check uppercase requirement
    if pwd_uppercase_min > 0 and uppercase_count < pwd_uppercase_min:
        errors.append(f"Password must contain at least {pwd_uppercase_min} uppercase letters")
    
    # Check lowercase requirement
    if pwd_lowercase_min > 0 and lowercase_count < pwd_lowercase_min:
        errors.append(f"Password must contain at least {pwd_lowercase_min} lowercase letters")
    
    # Check digit requirement
    if pwd_digits_min > 0 and digit_count < pwd_digits_min:
        errors.append(f"Password must contain at least {pwd_digits_min} digits")
    
    # Check special character requirement
    if pwd_special_min > 0:
        if special_count < pwd_special_min:
            errors.append(f"Password must contain at least {pwd_special_min} special characters")
        else:
            # Validate against allowed special characters
            for c in password:
                if not c.isalnum() and c not in pwd_special_allowed:
                    errors.append(f"Password contains disallowed special character: {c}")
                    break
    
    return errors
