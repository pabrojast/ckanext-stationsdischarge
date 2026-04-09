"""Validation schemas for hydro station actions."""

from ckan.plugins import toolkit

not_empty = toolkit.get_validator("not_empty")
not_missing = toolkit.get_validator("not_missing")
ignore_missing = toolkit.get_validator("ignore_missing")
unicode_safe = toolkit.get_validator("unicode_safe")
boolean_validator = toolkit.get_validator("boolean_validator")

from ckanext.stationsdischarge.validators import (
    valid_latitude,
    valid_longitude,
    valid_uuid,
    valid_curve_params_json,
)


def _station_name_validator(value, context):
    """Ensure station name (URL slug) is unique."""
    from ckanext.stationsdischarge import db as _db
    existing = _db.HydroStation.get(name=value)
    if existing:
        station_id = context.get("station_id")
        if not station_id or existing.id != station_id:
            raise toolkit.Invalid(
                f"A station with URL '{value}' already exists."
            )
    return value


def _station_id_validator(value, context):
    """Ensure station_id is unique."""
    from ckanext.stationsdischarge import db as _db
    existing = _db.HydroStation.get(station_id=value)
    if existing:
        station_id = context.get("station_id")
        if not station_id or existing.id != station_id:
            raise toolkit.Invalid(
                f"A station with ID '{value}' already exists."
            )
    return value


def station_create_schema():
    return {
        # Identity
        "title": [not_empty, unicode_safe],
        "name": [not_empty, unicode_safe, _station_name_validator],
        "station_id": [not_empty, unicode_safe, _station_id_validator],
        "owner_org": [not_empty, unicode_safe],
        "station_status": [not_empty, unicode_safe],
        "notes": [ignore_missing, unicode_safe],
        "tag_string": [ignore_missing, unicode_safe],
        # Location
        "latitude": [not_empty, valid_latitude],
        "longitude": [not_empty, valid_longitude],
        "river_name": [ignore_missing, unicode_safe],
        "basin_name": [ignore_missing, unicode_safe],
        "country": [ignore_missing, unicode_safe],
        "elevation_masl": [ignore_missing],
        # IoT
        "thingsboard_entity_id": [not_empty, unicode_safe, valid_uuid],
        "thingsboard_device_id": [ignore_missing, unicode_safe],
        "thingsboard_telemetry_key": [not_empty, unicode_safe],
        "observed_variable": [not_empty, unicode_safe],
        # Units
        "unit_level": [not_empty, unicode_safe],
        "unit_flow": [not_empty, unicode_safe],
        # Rating curve
        "curve_type": [not_empty, unicode_safe],
        "curve_params_json": [not_empty, unicode_safe],
        "curve_valid_from": [ignore_missing, unicode_safe],
        "curve_valid_to": [ignore_missing, unicode_safe],
        "curve_notes": [ignore_missing, unicode_safe],
        # Workflow
        "submission_status": [ignore_missing, unicode_safe],
    }


def station_update_schema():
    schema = station_create_schema()
    schema["id"] = [not_empty, unicode_safe]
    # On update, make some fields optional (they keep existing values)
    for field in ("title", "name", "station_id", "owner_org",
                  "station_status", "latitude", "longitude",
                  "thingsboard_entity_id", "thingsboard_telemetry_key",
                  "observed_variable", "unit_level", "unit_flow",
                  "curve_type", "curve_params_json"):
        schema[field] = [ignore_missing, unicode_safe]
    return schema
