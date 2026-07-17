"""FORTRESS_UNIFIED core package — shared infra for sniper/incubator/pine-sync."""
import logging

from . import config


def preflight_secrets() -> dict:
    """Check required + optional secrets, log warnings, never abort."""
    checks = {}
    for k, v in config.REQUIRED_SECRETS.items():
        ok = bool(v)
        checks[k] = ok
        if not ok:
            logging.getLogger("fortress").warning(f"SECRET MISSING (required): {k}")
    for k, v in config.OPTIONAL_SECRETS.items():
        ok = bool(v)
        checks[k] = ok
        if not ok:
            logging.getLogger("fortress").info(f"Secret not set (optional): {k}")
    return checks
