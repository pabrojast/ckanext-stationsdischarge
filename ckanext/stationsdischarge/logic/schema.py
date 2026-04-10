"""Validation schemas for hydro station actions."""

from ckan.plugins import toolkit
from ckan.lib.navl.dictization_functions import missing, StopOnError

not_empty = toolkit.get_validator("not_empty")
not_missing = toolkit.get_validator("not_missing")
ignore_missing = toolkit.get_validator("ignore_missing")
unicode_safe = toolkit.get_validator("unicode_safe")
boolean_validator = toolkit.get_validator("boolean_validator")

from ckanext.stationsdischarge.validators import (
    valid_curve_params_json,
)


def _navl_valid_latitude(key, data, errors, context):
    """Navl-compatible latitude validator."""
    value = data.get(key)
    if not value and value != 0:
        return
    try:
        v = float(value)
    except (ValueError, TypeError):
        errors[key].append("Latitude must be a decimal number (e.g. -33.59).")
        raise StopOnError
    if v < -90 or v > 90:
        errors[key].append("Latitude must be between -90 and 90.")
        raise StopOnError
    data[key] = str(v)


def _navl_valid_longitude(key, data, errors, context):
    """Navl-compatible longitude validator."""
    value = data.get(key)
    if not value and value != 0:
        return
    try:
        v = float(value)
    except (ValueError, TypeError):
        errors[key].append("Longitude must be a decimal number (e.g. -70.34).")
        raise StopOnError
    if v < -180 or v > 180:
        errors[key].append("Longitude must be between -180 and 180.")
        raise StopOnError
    data[key] = str(v)


import re
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _navl_valid_uuid(key, data, errors, context):
    """Navl-compatible UUID validator."""
    value = data.get(key)
    if not value:
        return
    value = value.strip()
    if not _UUID_RE.match(value):
        errors[key].append(
            "Must be a valid UUID (e.g. 784f394c-42b6-11ec-81d3-0242ac130003)."
        )
        raise StopOnError
    data[key] = value


def _navl_station_name_validator(key, data, errors, context):
    """Navl-compatible: ensure station name (URL slug) is unique."""
    value = data.get(key)
    if not value:
        return
    from ckanext.stationsdischarge import db as _db
    existing = _db.HydroStation.get(name=value)
    if existing:
        station_id = context.get("station_id")
        if not station_id or existing.id != station_id:
            errors[key].append(
                f"A station with URL '{value}' already exists."
            )
            raise StopOnError


def _navl_station_id_validator(key, data, errors, context):
    """Navl-compatible: ensure station_id is unique."""
    value = data.get(key)
    if not value:
        return
    from ckanext.stationsdischarge import db as _db
    existing = _db.HydroStation.get(station_id=value)
    if existing:
        station_id = context.get("station_id")
        if not station_id or existing.id != station_id:
            errors[key].append(
                f"A station with ID '{value}' already exists."
            )
            raise StopOnError


def station_create_schema():
    return {
        # Identity
        "title": [not_empty, unicode_safe],
        "name": [not_empty, unicode_safe, _navl_station_name_validator],
        "station_id": [not_empty, unicode_safe, _navl_station_id_validator],
        "owner_org": [not_empty, unicode_safe],
        "station_status": [not_empty, unicode_safe],
        "notes": [ignore_missing, unicode_safe],
        "tag_string": [ignore_missing, unicode_safe],
        # Location
        "latitude": [not_empty, _navl_valid_latitude],
        "longitude": [not_empty, _navl_valid_longitude],
        "river_name": [ignore_missing, unicode_safe],
        "basin_name": [ignore_missing, unicode_safe],
        "country": [ignore_missing, unicode_safe],
        "elevation_masl": [ignore_missing],
        # IoT
        "thingsboard_entity_id": [not_empty, unicode_safe, _navl_valid_uuid],
        "thingsboard_device_id": [ignore_missing, unicode_safe],
        "thingsboard_telemetry_key": [not_empty, unicode_safe],
        "observed_variable": [not_empty, unicode_safe],
        # Units
        "unit_level": [not_empty, unicode_safe],
        "unit_flow": [not_empty, unicode_safe],
        # Rating curve
        "curve_type": [not_empty, unicode_safe],
        "curve_params_json": [not_empty, unicode_safe, valid_curve_params_json],
        "curve_valid_from": [ignore_missing, unicode_safe],
        "curve_valid_to": [ignore_missing, unicode_safe],
        "curve_notes": [ignore_missing, unicode_safe],
        # Workflow
        "submission_status": [ignore_missing, unicode_safe],
    }


def station_update_schema():
    schema = station_create_schema()
    schema["id"] = [not_empty, unicode_safe]
    # On update, make fields optional but keep their validators
    for field in ("title", "name", "station_id", "owner_org",
                  "station_status", "latitude", "longitude",
                  "thingsboard_entity_id", "thingsboard_telemetry_key",
                  "observed_variable", "unit_level", "unit_flow",
                  "curve_type", "curve_params_json"):
        schema[field] = [ignore_missing] + schema[field]
    return schema
