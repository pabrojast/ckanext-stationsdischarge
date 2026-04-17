"""Custom validators for stationsdischarge."""

import logging
import re

from ckan.plugins import toolkit

log = logging.getLogger(__name__)

# ── Latitude / Longitude ────────────────────────────


def valid_latitude(value):
    """Validate that value is a decimal latitude in [-90, 90]."""
    if not value and value != 0:
        return value
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise toolkit.Invalid("Latitude must be a decimal number (e.g. -33.59).")
    if v < -90 or v > 90:
        raise toolkit.Invalid("Latitude must be between -90 and 90.")
    return str(v)


def valid_longitude(value):
    """Validate that value is a decimal longitude in [-180, 180]."""
    if not value and value != 0:
        return value
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise toolkit.Invalid("Longitude must be a decimal number (e.g. -70.34).")
    if v < -180 or v > 180:
        raise toolkit.Invalid("Longitude must be between -180 and 180.")
    return str(v)


# ── UUID (ThingsBoard IDs) ──────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def valid_uuid(value):
    """Validate that value looks like a UUID."""
    if not value:
        return value
    value = value.strip()
    if not _UUID_RE.match(value):
        raise toolkit.Invalid(
            "Must be a valid UUID (e.g. 784f394c-42b6-11ec-81d3-0242ac130003)."
        )
    return value
