"""Server-side validation for account passwords and vehicle plate numbers.

Kept as pure functions (no Flask/DB) so they're independently testable,
same reasoning as fees.py and rates.py.
"""

import re

PASSWORD_MIN_LENGTH = 8

# Indian standard plate format: 2-letter state code, 1-2 digit RTO code,
# 1-3 letter series, 4-digit number — e.g. KA01AB1234, MH12CD5678, DL01C1234.
# This intentionally does not cover the newer BH-series format
# (YYBHnnnnXX), which is a documented scope decision, not an oversight.
PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")


def normalize_plate(raw):
    """Upper-cases and strips spaces/hyphens so 'ka 01-ab 1234' and
    'KA01AB1234' are recognized as the same plate."""
    return re.sub(r"[\s-]", "", (raw or "").strip().upper())


def is_valid_plate(plate):
    return bool(PLATE_REGEX.match(plate))


def password_strength_error(password):
    """Returns a human-readable reason the password is too weak, or None if
    it's strong enough: at least 8 characters, with a lowercase letter, an
    uppercase letter, a digit, and a special character."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one digit"
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character"
    return None
