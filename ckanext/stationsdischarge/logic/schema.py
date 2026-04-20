"""Validation schemas for hydro station actions."""

from ckan.plugins import toolkit
from ckan.lib.navl.dictization_functions import missing, StopOnError

not_empty = toolkit.get_validator("not_empty")
not_missing = toolkit.get_validator("not_missing")
ignore_missing = toolkit.get_validator("ignore_missing")
unicode_safe = toolkit.get_validator("unicode_safe")
boolean_validator = toolkit.get_validator("boolean_validator")


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
        "thingsboard_entity_id": [ignore_missing, unicode_safe, _navl_valid_uuid],
        "thingsboard_device_id": [ignore_missing, unicode_safe],
        # Workflow
        "submission_status": [ignore_missing, unicode_safe],
    }


def station_update_schema():
    schema = station_create_schema()
    schema["id"] = [not_empty, unicode_safe]
    for field in ("title", "name", "station_id", "owner_org",
                  "station_status", "latitude", "longitude"):
        schema[field] = [ignore_missing] + schema[field]
    return schema


# ── Dataset schemas ──

def _navl_dataset_name_validator(key, data, errors, context):
    """Ensure dataset name (URL slug) is unique."""
    value = data.get(key)
    if not value:
        return
    from ckanext.stationsdischarge import db as _db
    existing = _db.HydroDataset.get(name=value)
    if existing:
        dataset_id = context.get("dataset_id")
        if not dataset_id or existing.id != dataset_id:
            errors[key].append(f"A dataset with URL '{value}' already exists.")
            raise StopOnError


def dataset_create_schema():
    return {
        "title": [not_empty, unicode_safe],
        "name": [not_empty, unicode_safe, _navl_dataset_name_validator],
        "description": [ignore_missing, unicode_safe],
        "owner_org": [ignore_missing, unicode_safe],
        "time_range": [ignore_missing, unicode_safe],
        "agg": [ignore_missing, unicode_safe],
        "interval_ms": [ignore_missing],
        "export_format": [ignore_missing, unicode_safe],
    }


def dataset_update_schema():
    schema = dataset_create_schema()
    schema["id"] = [not_empty, unicode_safe]
    for field in ("title", "name"):
        schema[field] = [ignore_missing] + schema[field]
    return schema
