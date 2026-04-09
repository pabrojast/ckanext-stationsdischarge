"""CKAN action functions for hydro stations (CRUD + list)."""

import datetime
import json
import logging
import uuid
import re

import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.logic import validate as validate_decorator

from ckanext.stationsdischarge import db as station_db
from ckanext.stationsdischarge.logic.schema import (
    station_create_schema,
    station_update_schema,
)
from ckanext.stationsdischarge.validators import (
    valid_latitude,
    valid_longitude,
    valid_uuid,
)

log = logging.getLogger(__name__)


def _generate_spatial(lat, lon):
    """Build GeoJSON Point from lat/lon."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return None
    return json.dumps({"type": "Point", "coordinates": [lon_f, lat_f]})


def _slugify(title):
    """Generate a URL-friendly slug from a title."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:100].strip("-")


def _validate_data(data_dict, schema, context):
    """Run validation and return cleaned data + errors."""
    errors = {}
    clean = {}
    for field, validators in schema.items():
        value = data_dict.get(field)
        field_errors = []
        for validator in validators:
            try:
                # Handle cross-field validators (4-arg signature)
                import inspect
                sig = inspect.signature(validator)
                if len(sig.parameters) >= 4:
                    fake_key = field
                    fake_data = {field: value}
                    fake_errors = {field: []}
                    validator(fake_key, fake_data, fake_errors, context)
                    value = fake_data.get(field, value)
                    field_errors.extend(fake_errors.get(field, []))
                elif len(sig.parameters) >= 2:
                    value = validator(value, context)
                else:
                    value = validator(value)
            except toolkit.Invalid as e:
                field_errors.append(str(e))
                break
        if field_errors:
            errors[field] = field_errors
        else:
            clean[field] = value
    return clean, errors


def station_create(context, data_dict):
    """Create a new hydro station.

    :param title: Station name (required)
    :param station_id: Unique station identifier (required)
    :param owner_org: Organization ID (required)
    :param latitude: Decimal latitude (required)
    :param longitude: Decimal longitude (required)
    :param ... (see schema for all fields)
    :returns: Station dict
    """
    toolkit.check_access("station_create", context, data_dict)

    # Auto-generate name from title if not provided
    if not data_dict.get("name"):
        data_dict["name"] = _slugify(data_dict.get("title", ""))

    schema = station_create_schema()
    clean, errors = _validate_data(data_dict, schema, context)

    if errors:
        raise toolkit.ValidationError(errors)

    # Generate spatial GeoJSON
    spatial = _generate_spatial(clean.get("latitude"), clean.get("longitude"))

    now = datetime.datetime.utcnow()
    user_obj = model.User.get(context.get("user"))

    station = station_db.HydroStation()
    station.id = str(uuid.uuid4())

    # Set all fields from cleaned data
    for field, value in clean.items():
        if hasattr(station, field) and value is not None:
            setattr(station, field, value)

    station.spatial = spatial
    station.user_id = user_obj.id if user_obj else None
    station.created = now
    station.modified = now

    if not station.submission_status:
        station.submission_status = "draft"

    # Handle elevation as float
    if data_dict.get("elevation_masl"):
        try:
            station.elevation_masl = float(data_dict["elevation_masl"])
        except (ValueError, TypeError):
            pass

    station.save()
    model.Session.commit()

    log.info("stationsdischarge: Created station '%s' (%s)",
             station.title, station.id)

    return station.as_dict()


def station_show(context, data_dict):
    """Show a hydro station by id or name.

    :param id: Station UUID or name/slug
    :returns: Station dict
    """
    station_ref = data_dict.get("id") or data_dict.get("name")
    if not station_ref:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    station = (station_db.HydroStation.get(id=station_ref)
               or station_db.HydroStation.get(name=station_ref)
               or station_db.HydroStation.get(station_id=station_ref))

    if not station:
        raise toolkit.ObjectNotFound(f"Station not found: {station_ref}")

    toolkit.check_access("station_show", context, data_dict)

    return station.as_dict()


def station_update(context, data_dict):
    """Update an existing hydro station.

    :param id: Station UUID (required)
    :param ... (fields to update)
    :returns: Updated station dict
    """
    station_id = data_dict.get("id")
    if not station_id:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    station = station_db.HydroStation.get(id=station_id)
    if not station:
        raise toolkit.ObjectNotFound(f"Station not found: {station_id}")

    toolkit.check_access("station_update", context, data_dict)

    # Pass station_id in context for uniqueness checks
    context["station_id"] = station.id

    schema = station_update_schema()
    clean, errors = _validate_data(data_dict, schema, context)

    if errors:
        raise toolkit.ValidationError(errors)

    # Handle submission workflow actions
    submission_action = data_dict.get("submission_action")
    if submission_action == "submit":
        clean["submission_status"] = "pending"
        clean["submitted_at"] = datetime.datetime.utcnow()
    elif submission_action == "approve":
        from ckanext.stationsdischarge.auth import _is_sysadmin
        if not _is_sysadmin(context):
            raise toolkit.NotAuthorized("Only sysadmins can approve stations.")
        clean["submission_status"] = "approved"
        clean["reviewed_at"] = datetime.datetime.utcnow()
        user_obj = model.User.get(context.get("user"))
        clean["reviewed_by"] = user_obj.id if user_obj else None
    elif submission_action == "reject":
        from ckanext.stationsdischarge.auth import _is_sysadmin
        if not _is_sysadmin(context):
            raise toolkit.NotAuthorized("Only sysadmins can reject stations.")
        clean["submission_status"] = "rejected"
        clean["reviewed_at"] = datetime.datetime.utcnow()
        user_obj = model.User.get(context.get("user"))
        clean["reviewed_by"] = user_obj.id if user_obj else None
    elif submission_action == "draft":
        clean["submission_status"] = "draft"

    # Update fields
    for field, value in clean.items():
        if field == "id":
            continue
        if hasattr(station, field) and value is not None:
            setattr(station, field, value)

    # Regenerate spatial if lat/lon changed
    lat = clean.get("latitude") or station.latitude
    lon = clean.get("longitude") or station.longitude
    if lat and lon:
        station.spatial = _generate_spatial(lat, lon)

    # Handle elevation
    if "elevation_masl" in data_dict:
        try:
            station.elevation_masl = float(data_dict["elevation_masl"]) if data_dict["elevation_masl"] else None
        except (ValueError, TypeError):
            pass

    station.modified = datetime.datetime.utcnow()
    station.save()
    model.Session.commit()

    log.info("stationsdischarge: Updated station '%s' (%s)",
             station.title, station.id)

    return station.as_dict()


def station_delete(context, data_dict):
    """Delete a hydro station.

    :param id: Station UUID (required)
    :returns: Empty dict
    """
    station_id = data_dict.get("id")
    if not station_id:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    station = station_db.HydroStation.get(id=station_id)
    if not station:
        raise toolkit.ObjectNotFound(f"Station not found: {station_id}")

    toolkit.check_access("station_delete", context, data_dict)

    station.delete()
    model.Session.commit()

    log.info("stationsdischarge: Deleted station '%s' (%s)",
             station.title, station_id)

    return {}


def station_list(context, data_dict):
    """List hydro stations with optional filters.

    :param org_id: Filter by organization
    :param station_status: Filter by station status (active/inactive/maintenance)
    :param submission_status: Filter by submission status
    :param q: Search query
    :param order_by: Sort field (modified, title, created)
    :param limit: Max results (default 100)
    :param offset: Offset for pagination
    :returns: Dict with 'results' list and 'count' total
    """
    toolkit.check_access("station_list", context, data_dict)

    user = context.get("user")
    is_sysadmin = False
    user_obj = None
    if user:
        user_obj = model.User.get(user)
        is_sysadmin = user_obj and user_obj.sysadmin

    results, total = station_db.HydroStation.list_stations(
        org_id=data_dict.get("org_id"),
        station_status=data_dict.get("station_status"),
        submission_status=data_dict.get("submission_status"),
        q=data_dict.get("q"),
        order_by=data_dict.get("order_by", "modified"),
        limit=int(data_dict.get("limit", 100)),
        offset=int(data_dict.get("offset", 0)),
    )

    # Filter by visibility unless sysadmin
    station_dicts = []
    for s in results:
        d = s.as_dict()
        if d["submission_status"] == "approved":
            station_dicts.append(d)
        elif is_sysadmin:
            station_dicts.append(d)
        elif user_obj and d["user_id"] == user_obj.id:
            station_dicts.append(d)

    return {
        "results": station_dicts,
        "count": total,
    }
