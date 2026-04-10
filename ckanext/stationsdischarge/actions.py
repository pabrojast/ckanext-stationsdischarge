"""CKAN action functions for hydro stations (CRUD + list + telemetry)."""

import datetime
import json
import logging
import math
import os
import time
import urllib.request
import urllib.error
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
    """Run validation using CKAN's native navl validate."""
    from ckan.lib.navl.dictization_functions import validate
    data, errors = validate(data_dict, schema, context)
    return data, errors


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

    try:
        station.save()
        model.Session.commit()
    except Exception as e:
        model.Session.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise toolkit.ValidationError(
                {"name": ["A station with this name or ID already exists."]}
            )
        raise

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
    try:
        station.save()
        model.Session.commit()
    except Exception as e:
        model.Session.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise toolkit.ValidationError(
                {"name": ["A station with this name or ID already exists."]}
            )
        raise

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

    try:
        limit = int(data_dict.get("limit", 100))
        offset = int(data_dict.get("offset", 0))
    except (ValueError, TypeError):
        raise toolkit.ValidationError({
            "message": ["limit and offset must be valid integers"]
        })

    results, total = station_db.HydroStation.list_stations(
        org_id=data_dict.get("org_id"),
        station_status=data_dict.get("station_status"),
        submission_status=data_dict.get("submission_status"),
        q=data_dict.get("q"),
        order_by=data_dict.get("order_by", "modified"),
        limit=limit,
        offset=offset,
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
        "count": len(station_dicts),
    }


def _get_tb_config():
    """Return ThingsBoard URL and API key from environment."""
    tb_url = os.environ.get(
        "CKANEXT__STATIONSDISCHARGE__TB_URL",
        os.environ.get("TB_URL", "https://tb.ihp-wins.unesco.org"),
    )
    tb_api_key = os.environ.get(
        "CKANEXT__STATIONSDISCHARGE__TB_API_KEY",
        os.environ.get("TB_API_KEY", ""),
    )
    return tb_url, tb_api_key


def _tb_request(tb_url, tb_api_key, api_path):
    """Make an authenticated request to ThingsBoard and return parsed JSON."""
    url = tb_url.rstrip("/") + api_path
    req = urllib.request.Request(url)
    req.add_header("X-Authorization", "ApiKey " + tb_api_key)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        log.error("ThingsBoard API error %s: %s", e.code, body)
        raise toolkit.ValidationError(
            {"thingsboard": ["ThingsBoard API returned HTTP %s" % e.code]}
        )
    except urllib.error.URLError as e:
        log.error("ThingsBoard connection error: %s", e.reason)
        raise toolkit.ValidationError(
            {"thingsboard": ["Cannot connect to ThingsBoard: %s" % e.reason]}
        )


def _resolve_station(data_dict):
    """Resolve a station from id/name/station_id, or raise."""
    station_ref = data_dict.get("id") or data_dict.get("name")
    if not station_ref:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    station = (station_db.HydroStation.get(id=station_ref)
               or station_db.HydroStation.get(name=station_ref)
               or station_db.HydroStation.get(station_id=station_ref))

    if not station:
        raise toolkit.ObjectNotFound("Station not found: %s" % station_ref)
    return station


def _check_station_access(context, station):
    """Run access check for reading a station."""
    toolkit.check_access("station_show", context, {
        "id": station.id,
        "submission_status": station.submission_status,
        "user_id": station.user_id,
        "owner_org": station.owner_org,
    })


# ── Rating curve calculation ─────────────────────────

def _compute_discharge(h, curve_type, curve_params):
    """Apply the rating curve to convert water level *h* to discharge *Q*.

    Supported curve types:
    - **power**: Q = a * (h - h0)^b
    - **linear_segments**: piecewise Q = slope*h + intercept
    - **table_interpolation**: linear interpolation on an H-Q table

    Returns Q (float) or None if computation is not possible.
    """
    if h is None or curve_params is None:
        return None

    try:
        h = float(h)
    except (ValueError, TypeError):
        return None

    if curve_type == "power":
        a = float(curve_params.get("a", 0))
        b = float(curve_params.get("b", 1))
        h0 = float(curve_params.get("h0", 0))
        diff = h - h0
        if diff < 0:
            return 0.0
        return round(a * math.pow(diff, b), 4)

    if curve_type == "linear_segments":
        segments = curve_params.get("segments", [])
        for seg in segments:
            h_min = float(seg.get("h_min", 0))
            h_max = float(seg.get("h_max", float("inf")))
            if h_min <= h <= h_max:
                slope = float(seg.get("slope", 0))
                intercept = float(seg.get("intercept", 0))
                return round(slope * h + intercept, 4)
        # Outside all segments — extrapolate from last
        if segments:
            seg = segments[-1]
            slope = float(seg.get("slope", 0))
            intercept = float(seg.get("intercept", 0))
            return round(slope * h + intercept, 4)
        return None

    if curve_type == "table_interpolation":
        table = curve_params.get("table", [])
        if not table:
            return None
        table = sorted(table, key=lambda p: float(p["h"]))
        # Below table range
        if h <= float(table[0]["h"]):
            return float(table[0]["q"])
        # Above table range
        if h >= float(table[-1]["h"]):
            return float(table[-1]["q"])
        # Interpolate
        for i in range(len(table) - 1):
            h1 = float(table[i]["h"])
            h2 = float(table[i + 1]["h"])
            if h1 <= h <= h2:
                q1 = float(table[i]["q"])
                q2 = float(table[i + 1]["q"])
                if h2 == h1:
                    return q1
                frac = (h - h1) / (h2 - h1)
                return round(q1 + frac * (q2 - q1), 4)
        return None

    return None


def _fetch_telemetry(tb_url, tb_api_key, entity_id, keys, start_ts=None,
                     end_ts=None, limit=100):
    """Fetch telemetry from ThingsBoard for a device."""
    if start_ts and end_ts:
        api_path = (
            "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
            "?keys=%s&startTs=%s&endTs=%s&limit=%s"
            % (entity_id, keys, start_ts, end_ts, limit)
        )
    else:
        api_path = (
            "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
            "?keys=%s" % (entity_id, keys)
        )
    return _tb_request(tb_url, tb_api_key, api_path)


# ── Actions ──────────────────────────────────────────

def station_telemetry(context, data_dict):
    """Fetch latest telemetry data from ThingsBoard for a station.

    :param id: Station UUID or name/slug (required)
    :param keys: Comma-separated telemetry keys (optional, defaults to station's configured key)
    :param start_ts: Start timestamp in ms (optional, for historical data)
    :param end_ts: End timestamp in ms (optional, for historical data)
    :param limit: Max data points (default 100)
    :returns: Dict with station info and telemetry data
    """
    station = _resolve_station(data_dict)
    _check_station_access(context, station)

    tb_url, tb_api_key = _get_tb_config()
    if not tb_api_key:
        raise toolkit.ValidationError(
            {"thingsboard": ["ThingsBoard API key not configured (TB_API_KEY env var)"]}
        )

    entity_id = station.thingsboard_entity_id
    if not entity_id:
        raise toolkit.ValidationError(
            {"thingsboard_entity_id": ["Station has no ThingsBoard entity configured"]}
        )

    keys = data_dict.get("keys") or station.thingsboard_telemetry_key or "fDistance"

    try:
        limit = int(data_dict.get("limit", 100))
    except (ValueError, TypeError):
        limit = 100

    telemetry_raw = _fetch_telemetry(
        tb_url, tb_api_key, entity_id, keys,
        start_ts=data_dict.get("start_ts"),
        end_ts=data_dict.get("end_ts"),
        limit=limit,
    )

    return {
        "station_id": station.station_id,
        "station_name": station.name,
        "thingsboard_entity_id": entity_id,
        "telemetry_key": keys,
        "telemetry": telemetry_raw,
    }


def station_discharge(context, data_dict):
    """Fetch telemetry and compute discharge using the station rating curve.

    :param id: Station UUID or name/slug (required)
    :param keys: Telemetry key for water level (optional, defaults to station config)
    :param start_ts: Start timestamp in ms (optional)
    :param end_ts: End timestamp in ms (optional)
    :param limit: Max data points (default 100)
    :returns: Dict with raw telemetry, computed discharge, and curve info
    """
    station = _resolve_station(data_dict)
    _check_station_access(context, station)

    tb_url, tb_api_key = _get_tb_config()
    if not tb_api_key:
        raise toolkit.ValidationError(
            {"thingsboard": ["ThingsBoard API key not configured (TB_API_KEY env var)"]}
        )

    entity_id = station.thingsboard_entity_id
    if not entity_id:
        raise toolkit.ValidationError(
            {"thingsboard_entity_id": ["Station has no ThingsBoard entity configured"]}
        )

    keys = data_dict.get("keys") or station.thingsboard_telemetry_key or "fDistance"

    try:
        limit = int(data_dict.get("limit", 100))
    except (ValueError, TypeError):
        limit = 100

    telemetry_raw = _fetch_telemetry(
        tb_url, tb_api_key, entity_id, keys,
        start_ts=data_dict.get("start_ts"),
        end_ts=data_dict.get("end_ts"),
        limit=limit,
    )

    # Parse curve params
    curve_type = station.curve_type
    curve_params = None
    if station.curve_params_json:
        try:
            curve_params = json.loads(station.curve_params_json) if isinstance(
                station.curve_params_json, str) else station.curve_params_json
        except (json.JSONDecodeError, TypeError):
            pass

    # Apply rating curve to each telemetry point
    discharge_series = {}
    for tel_key, points in telemetry_raw.items():
        discharge_points = []
        for point in points:
            h_val = point.get("value")
            ts = point.get("ts")
            q = _compute_discharge(h_val, curve_type, curve_params)
            discharge_points.append({
                "ts": ts,
                "h": float(h_val) if h_val is not None else None,
                "q": q,
            })
        discharge_series[tel_key] = discharge_points

    return {
        "station_id": station.station_id,
        "station_name": station.name,
        "title": station.title,
        "unit_level": station.unit_level or "m",
        "unit_flow": station.unit_flow or "m3/s",
        "curve_type": curve_type,
        "curve_params": curve_params,
        "thingsboard_entity_id": entity_id,
        "telemetry_key": keys,
        "telemetry": telemetry_raw,
        "discharge": discharge_series,
    }


def station_geojson(context, data_dict):
    """Return all approved stations as a GeoJSON FeatureCollection.

    :param org_id: Filter by organization (optional)
    :param station_status: Filter by station status (optional)
    :param q: Search query (optional)
    :param include_telemetry: If "true", include latest telemetry value (optional)
    :param start_ts: Start timestamp in ms — when given with include_telemetry, fetch series (optional)
    :param end_ts: End timestamp in ms (optional)
    :param limit: Max telemetry points per station (default 1 without time range, 100 with)
    :returns: GeoJSON FeatureCollection dict
    """
    toolkit.check_access("station_geojson", context, data_dict)

    results, _total = station_db.HydroStation.list_stations(
        org_id=data_dict.get("org_id"),
        station_status=data_dict.get("station_status"),
        submission_status="approved",
        q=data_dict.get("q"),
        limit=10000,
        offset=0,
    )

    include_telemetry = str(data_dict.get("include_telemetry", "")).lower() == "true"
    tb_url, tb_api_key = None, None
    start_ts = data_dict.get("start_ts") or None
    end_ts = data_dict.get("end_ts") or None
    has_time_range = bool(start_ts and end_ts)

    try:
        tel_limit = int(data_dict.get("limit", 100 if has_time_range else 1))
    except (ValueError, TypeError):
        tel_limit = 1

    if include_telemetry:
        tb_url, tb_api_key = _get_tb_config()

    features = []
    for station in results:
        lat = station.latitude
        lon = station.longitude
        if lat is None or lon is None:
            continue

        props = {
            "id": station.id,
            "title": station.title,
            "name": station.name,
            "station_id": station.station_id,
            "station_status": station.station_status,
            "river_name": station.river_name,
            "basin_name": station.basin_name,
            "country": station.country,
            "elevation_masl": station.elevation_masl,
            "observed_variable": station.observed_variable,
            "unit_level": station.unit_level,
            "unit_flow": station.unit_flow,
            "curve_type": station.curve_type,
        }

        # Parse curve for discharge computation
        curve_params = None
        if station.curve_params_json and station.curve_type:
            try:
                curve_params = json.loads(station.curve_params_json)
            except (json.JSONDecodeError, TypeError):
                pass

        if include_telemetry and tb_api_key and station.thingsboard_entity_id:
            tel_key = station.thingsboard_telemetry_key or "fDistance"
            try:
                tel = _fetch_telemetry(
                    tb_url, tb_api_key,
                    station.thingsboard_entity_id,
                    tel_key,
                    start_ts=start_ts if has_time_range else None,
                    end_ts=end_ts if has_time_range else None,
                    limit=tel_limit,
                )
                for k, v in tel.items():
                    if v:
                        # Always include latest value
                        props["latest_value"] = float(v[0].get("value", 0))
                        props["latest_ts"] = v[0].get("ts")
                        props["telemetry_key"] = k

                        # Compute discharge for latest value
                        if curve_params:
                            q = _compute_discharge(
                                props["latest_value"],
                                station.curve_type, curve_params)
                            if q is not None:
                                props["latest_discharge"] = q

                        # Include full series when time range given
                        if has_time_range and len(v) > 1:
                            series = []
                            for pt in v:
                                h_val = float(pt.get("value", 0))
                                entry = {
                                    "ts": pt.get("ts"),
                                    "h": h_val,
                                }
                                if curve_params:
                                    q = _compute_discharge(
                                        h_val, station.curve_type, curve_params)
                                    if q is not None:
                                        entry["q"] = q
                                series.append(entry)
                            props["telemetry_series"] = series
                        break
            except Exception as e:
                log.debug("GeoJSON: skipping telemetry for %s: %s",
                          station.name, e)

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            },
            "properties": props,
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def station_discharge_csv(context, data_dict):
    """Return discharge data formatted for CSV output.

    Same params as station_discharge. Returns a dict with 'header' and 'rows'.
    """
    station = _resolve_station(data_dict)
    _check_station_access(context, station)

    # Re-use station_discharge logic
    discharge_data = station_discharge(context, data_dict)

    unit_level = discharge_data.get("unit_level", "m")
    unit_flow = discharge_data.get("unit_flow", "m3/s")

    header = ["timestamp_ms", "datetime_utc",
              "water_level_%s" % unit_level,
              "discharge_%s" % unit_flow]
    rows = []

    for _tel_key, points in discharge_data.get("discharge", {}).items():
        for pt in points:
            ts = pt.get("ts")
            h = pt.get("h")
            q = pt.get("q")
            dt_str = ""
            if ts:
                try:
                    dt = datetime.datetime.utcfromtimestamp(int(ts) / 1000.0)
                    dt_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, TypeError, OSError):
                    pass
            rows.append([
                str(ts or ""),
                dt_str,
                str(h) if h is not None else "",
                str(q) if q is not None else "",
            ])

    return {
        "station_name": station.name,
        "station_id": station.station_id,
        "title": station.title,
        "header": header,
        "rows": rows,
    }
