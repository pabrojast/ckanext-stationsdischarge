"""CKAN action functions for hydro stations (CRUD + list + telemetry)."""

import datetime
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import re

import ckan.model as model
import ckan.plugins.toolkit as toolkit

from ckanext.stationsdischarge import db as station_db
from ckanext.stationsdischarge.logic.schema import (
    station_create_schema,
    station_update_schema,
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


def _save_telemetry_keys(station_id, keys_list):
    """Replace telemetry keys for a station.

    keys_list is a list of dicts with: telemetry_key, label, unit, variable_type, sort_order
    """
    station_db.StationTelemetryKey.delete_by_station(station_id)
    for i, key_data in enumerate(keys_list or []):
        if not key_data.get("telemetry_key"):
            continue
        tk = station_db.StationTelemetryKey()
        tk.id = str(uuid.uuid4())
        tk.station_id = station_id
        tk.telemetry_key = key_data["telemetry_key"]
        tk.label = key_data.get("label", "")
        tk.unit = key_data.get("unit", "")
        tk.variable_type = key_data.get("variable_type", "")
        tk.sort_order = key_data.get("sort_order", i)
        tk.save()
    model.Session.commit()


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

    # Handle submission workflow actions
    submission_action = data_dict.get("submission_action")
    if submission_action == "submit":
        station.submission_status = "pending"
        station.submitted_at = now
    elif submission_action == "publish":
        from ckanext.stationsdischarge.auth import _is_sysadmin
        if _is_sysadmin(context):
            station.submission_status = "approved"
            station.reviewed_at = now
            station.reviewed_by = user_obj.id if user_obj else None

    if "elevation_masl" in data_dict:
        station.elevation_masl = clean.get("elevation_masl")

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

    # Save telemetry keys
    _save_telemetry_keys(station.id, data_dict.get("telemetry_keys", []))

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
    elif submission_action == "publish":
        from ckanext.stationsdischarge.auth import _is_sysadmin
        if not _is_sysadmin(context):
            raise toolkit.NotAuthorized("Only sysadmins can publish stations directly.")
        clean["submission_status"] = "approved"
        clean["reviewed_at"] = datetime.datetime.utcnow()
        user_obj = model.User.get(context.get("user"))
        clean["reviewed_by"] = user_obj.id if user_obj else None
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

    if "elevation_masl" in data_dict:
        station.elevation_masl = clean.get("elevation_masl")

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

    # Update telemetry keys if provided
    if "telemetry_keys" in data_dict:
        _save_telemetry_keys(station.id, data_dict["telemetry_keys"])

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

    station_db.StationTelemetryKey.delete_by_station(station.id)
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

    log.debug("ThingsBoard request: %s", url)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        log.error("ThingsBoard API error %s: %s", e.code, body)
        # Include the TB error body so the user can see what went wrong
        error_msg = "ThingsBoard API returned HTTP %s" % e.code
        if body:
            try:
                tb_error = json.loads(body)
                error_msg += ": " + tb_error.get("message", body[:200])
            except Exception:
                error_msg += ": " + body[:200]
        raise toolkit.ValidationError(
            {"thingsboard": [error_msg]}
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


# ── Time range presets ───────────────────────────────

_TIME_RANGE_PRESETS = {
    "1h":  {"hours": 1,     "limit": 500,  "agg": None,  "interval": None},
    "6h":  {"hours": 6,     "limit": 1000, "agg": None,  "interval": None},
    "24h": {"hours": 24,    "limit": 2000, "agg": None,  "interval": None},
    "7d":  {"hours": 168,   "limit": 5000, "agg": None,  "interval": None},
    "30d": {"hours": 720,   "limit": 744,  "agg": "AVG", "interval": 3600000},
    "90d": {"hours": 2160,  "limit": 720,  "agg": "AVG", "interval": 10800000},
    "6m":  {"hours": 4380,  "limit": 180,  "agg": "AVG", "interval": 86400000},
    "1y":  {"hours": 8760,  "limit": 366,  "agg": "AVG", "interval": 86400000},
}


def _resolve_time_range(data_dict):
    """Resolve time_range shortcut into start_ts, end_ts, limit, agg, interval."""
    time_range = str(data_dict.get("time_range", "")).strip().lower()
    preset = _TIME_RANGE_PRESETS.get(time_range) if time_range else None

    now_ms = int(time.time() * 1000)

    if preset:
        start_ts = str(now_ms - preset["hours"] * 3600 * 1000)
        end_ts = str(now_ms)
        default_limit = preset["limit"]
        default_agg = preset["agg"]
        default_interval = preset["interval"]
    else:
        start_ts = data_dict.get("start_ts") or None
        end_ts = data_dict.get("end_ts") or None
        default_limit = 100
        default_agg = None
        default_interval = None

    try:
        limit = int(data_dict.get("limit") or default_limit)
    except (ValueError, TypeError):
        limit = default_limit

    agg = data_dict.get("agg") or default_agg
    if agg and agg.upper() not in ("AVG", "MIN", "MAX", "SUM", "COUNT", "NONE"):
        agg = None

    interval = data_dict.get("interval") or default_interval
    if interval:
        try:
            interval = int(interval)
        except (ValueError, TypeError):
            interval = default_interval

    return {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "limit": limit,
        "agg": agg.upper() if agg else None,
        "interval": interval,
        "time_range": time_range or None,
    }


def _fetch_telemetry(tb_url, tb_api_key, entity_id, keys, start_ts=None,
                     end_ts=None, limit=100, agg=None, interval=None):
    """Fetch telemetry from ThingsBoard for a device.

    When *agg* and *interval* are provided, ThingsBoard returns aggregated
    values (e.g. hourly/daily averages) which dramatically reduces payload
    for long time ranges.

    If aggregation fails (HTTP 400), the function falls back to raw data
    with a higher limit, since some TB versions/instances do not support
    the agg/interval parameters on the timeseries endpoint.
    """
    safe_id = urllib.parse.quote(str(entity_id), safe="-")
    if "/" in entity_id or ".." in entity_id:
        raise toolkit.ValidationError({"thingsboard_entity_id": "Invalid entity ID"})

    safe_keys = urllib.parse.quote(str(keys), safe=",")

    def _build_url(use_agg=False):
        """Build the ThingsBoard API URL."""
        if start_ts and end_ts:
            if use_agg and agg and interval:
                # Aggregation mode: don't send limit, TB ignores it and
                # some versions reject it alongside agg/interval.
                return (
                    "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
                    "?keys=%s&startTs=%s&endTs=%s"
                    "&agg=%s&interval=%s"
                    % (safe_id, safe_keys, str(start_ts), str(end_ts),
                       urllib.parse.quote(str(agg), safe=""), int(interval))
                )
            else:
                return (
                    "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
                    "?keys=%s&startTs=%s&endTs=%s&limit=%s"
                    % (safe_id, safe_keys, str(start_ts), str(end_ts), limit)
                )
        else:
            return (
                "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
                "?keys=%s" % (safe_id, safe_keys)
            )

    # ── Attempt 1: with aggregation (if requested) ──
    if agg and interval and start_ts and end_ts:
        api_path = _build_url(use_agg=True)
        log.debug("Fetching telemetry WITH aggregation: keys=%s agg=%s interval=%s",
                  keys, agg, interval)
        try:
            return _tb_request(tb_url, tb_api_key, api_path)
        except toolkit.ValidationError as e:
            # If aggregation fails, log and fall back to raw data
            log.warning(
                "Aggregated telemetry failed (will retry without aggregation): %s",
                str(e.error_dict.get("thingsboard", ["unknown"])[0]) if hasattr(e, 'error_dict') else str(e)
            )

    # ── Attempt 2: raw data without aggregation ──
    api_path = _build_url(use_agg=False)
    log.debug("Fetching telemetry WITHOUT aggregation: keys=%s limit=%s", keys, limit)
    return _tb_request(tb_url, tb_api_key, api_path)


# ── Actions ──────────────────────────────────────────

def station_fetch_tb_metadata(context, data_dict):
    """Fetch device metadata from ThingsBoard to auto-fill station form.

    :param entity_id: ThingsBoard device UUID (required)
    :returns: Dict with device info, attributes, and available telemetry keys
    """
    toolkit.check_access("station_create", context, data_dict)

    entity_id = data_dict.get("entity_id", "").strip()
    if not entity_id:
        raise toolkit.ValidationError({"entity_id": ["Missing value"]})

    tb_url, tb_api_key = _get_tb_config()
    if not tb_api_key:
        raise toolkit.ValidationError(
            {"thingsboard": ["ThingsBoard API key not configured"]}
        )

    safe_id = urllib.parse.quote(str(entity_id), safe="-")

    # 1. Get device info
    device_info = {}
    try:
        device = _tb_request(tb_url, tb_api_key, "/api/device/%s" % safe_id)
        device_info = {
            "name": device.get("name", ""),
            "label": device.get("label", ""),
            "type": device.get("type", ""),
        }
        additional = device.get("additionalInfo") or {}
        if additional.get("description"):
            device_info["description"] = additional["description"]
        if additional.get("gateway"):
            device_info["gateway"] = additional["gateway"]
    except Exception as e:
        log.warning("TB: Could not fetch device info: %s", e)

    # 2. Get server-scope attributes (lat, lon, etc.)
    attributes = {}
    try:
        attrs = _tb_request(
            tb_url, tb_api_key,
            "/api/plugins/telemetry/DEVICE/%s/values/attributes/SERVER_SCOPE" % safe_id
        )
        for attr in attrs:
            attributes[attr.get("key", "")] = attr.get("value")
    except Exception as e:
        log.warning("TB: Could not fetch attributes: %s", e)

    # Also try CLIENT_SCOPE and SHARED_SCOPE for lat/lon
    for scope in ("CLIENT_SCOPE", "SHARED_SCOPE"):
        try:
            attrs = _tb_request(
                tb_url, tb_api_key,
                "/api/plugins/telemetry/DEVICE/%s/values/attributes/%s" % (safe_id, scope)
            )
            for attr in attrs:
                key = attr.get("key", "")
                if key not in attributes:
                    attributes[key] = attr.get("value")
        except Exception:
            pass

    # 3. Get available telemetry keys
    telemetry_keys = []
    try:
        keys = _tb_request(
            tb_url, tb_api_key,
            "/api/plugins/telemetry/DEVICE/%s/keys/timeseries" % safe_id
        )
        if isinstance(keys, list):
            telemetry_keys = keys
    except Exception as e:
        log.warning("TB: Could not fetch telemetry keys: %s", e)

    return {
        "device": device_info,
        "attributes": attributes,
        "telemetry_keys": telemetry_keys,
    }

def station_telemetry(context, data_dict):
    """Fetch latest telemetry data from ThingsBoard for a station.

    :param id: Station UUID or name/slug (required)
    :param keys: Comma-separated telemetry keys (optional, defaults to all station keys)
    :param start_ts: Start timestamp in ms (optional, for historical data)
    :param end_ts: End timestamp in ms (optional, for historical data)
    :param time_range: Shortcut preset: 1h, 6h, 24h, 7d, 30d, 90d, 6m, 1y
    :param agg: ThingsBoard aggregation: AVG, MIN, MAX, SUM, COUNT
    :param interval: Aggregation interval in ms
    :param limit: Max data points (default depends on range)
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

    keys = data_dict.get("keys")
    if not keys:
        keys_list = station_db.StationTelemetryKey.get_by_station(station.id)
        keys = ",".join(k.telemetry_key for k in keys_list) if keys_list else ""
    if not keys:
        raise toolkit.ValidationError(
            {"telemetry_keys": ["Station has no telemetry keys configured"]}
        )

    tr = _resolve_time_range(data_dict)

    telemetry_raw = _fetch_telemetry(
        tb_url, tb_api_key, entity_id, keys,
        start_ts=tr["start_ts"],
        end_ts=tr["end_ts"],
        limit=tr["limit"],
        agg=tr["agg"],
        interval=tr["interval"],
    )

    result = {
        "station_id": station.station_id,
        "station_name": station.name,
        "thingsboard_entity_id": entity_id,
        "telemetry_keys": keys,
        "telemetry": telemetry_raw,
    }
    if tr["agg"]:
        result["aggregation"] = tr["agg"]
        result["interval_ms"] = tr["interval"]
    if tr["time_range"]:
        result["time_range"] = tr["time_range"]

    return result



def station_geojson(context, data_dict):
    """Return all approved stations as a GeoJSON FeatureCollection.

    :param org_id: Filter by organization (optional)
    :param station_status: Filter by station status (optional)
    :param q: Search query (optional)
    :param include_telemetry: If "true", include latest telemetry value (optional)
    :param start_ts: Start timestamp in ms (optional)
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
        }

        if include_telemetry and tb_api_key and station.thingsboard_entity_id:
            # Get all telemetry keys for this station
            keys_list = station_db.StationTelemetryKey.get_by_station(station.id)
            tel_keys = ",".join(k.telemetry_key for k in keys_list) if keys_list else ""

            if tel_keys:
                try:
                    tel = _fetch_telemetry(
                        tb_url, tb_api_key,
                        station.thingsboard_entity_id,
                        tel_keys,
                        start_ts=start_ts if has_time_range else None,
                        end_ts=end_ts if has_time_range else None,
                        limit=tel_limit,
                    )
                    latest_values = {}
                    for k, v in tel.items():
                        if v:
                            latest_values[k] = {
                                "value": float(v[0].get("value", 0)),
                                "ts": v[0].get("ts"),
                            }
                            if has_time_range and len(v) > 1:
                                latest_values[k]["series"] = [
                                    {"ts": pt.get("ts"), "value": float(pt.get("value", 0))}
                                    for pt in v
                                ]
                    if latest_values:
                        props["telemetry"] = latest_values
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


# ── Dataset Actions ─────────────────────────────────────

def _save_dataset_stations(dataset_id, station_ids):
    """Replace all stations for a dataset."""
    station_db.HydroDatasetStation.delete_by_dataset(dataset_id)
    for idx, sid in enumerate(station_ids):
        st = station_db.HydroStation.get(id=sid)
        if not st:
            st = station_db.HydroStation.get(name=sid)
        if st:
            assoc = station_db.HydroDatasetStation(
                dataset_id=dataset_id,
                station_id=st.id,
                sort_order=idx,
            )
            model.Session.add(assoc)


def dataset_create(context, data_dict):
    """Create a new dataset (station group).

    :param title: Dataset title (required)
    :param name: URL slug (optional, auto-generated from title)
    :param description: Dataset description
    :param owner_org: Organization ID
    :param time_range: Default time range preset (1h, 24h, 7d, etc.)
    :param agg: Default aggregation (AVG, MIN, MAX)
    :param interval_ms: Default aggregation interval in ms
    :param export_format: Preferred export format (geojson, csv)
    :param station_ids: List of station IDs to include
    :returns: Dataset dict
    """
    toolkit.check_access("dataset_create", context, data_dict)

    from ckanext.stationsdischarge.logic.schema import dataset_create_schema
    data, errors = _validate_data(data_dict, dataset_create_schema(), context)
    if errors:
        raise toolkit.ValidationError(errors)

    if not data.get("name"):
        data["name"] = _slugify(data["title"])
        base = data["name"]
        counter = 1
        while station_db.HydroDataset.get(name=data["name"]):
            data["name"] = f"{base}-{counter}"
            counter += 1

    user_obj = model.User.get(context.get("user"))

    ds = station_db.HydroDataset(
        title=data["title"],
        name=data["name"],
        description=data.get("description", ""),
        owner_org=data.get("owner_org", ""),
        time_range=data.get("time_range", "24h"),
        agg=data.get("agg", ""),
        interval_ms=data.get("interval_ms"),
        export_format=data.get("export_format", "geojson"),
        user_id=user_obj.id if user_obj else None,
    )
    model.Session.add(ds)
    model.Session.flush()

    station_ids = data_dict.get("station_ids") or []
    if isinstance(station_ids, str):
        station_ids = [s.strip() for s in station_ids.split(",") if s.strip()]
    _save_dataset_stations(ds.id, station_ids)

    model.Session.commit()
    return ds.as_dict()


def dataset_show(context, data_dict):
    """Show a dataset by ID or name.

    :param id: Dataset UUID or name/slug (required)
    :returns: Dataset dict with stations
    """
    ds_id = data_dict.get("id") or data_dict.get("name")
    if not ds_id:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    ds = station_db.HydroDataset.get(id=ds_id)
    if not ds:
        ds = station_db.HydroDataset.get(name=ds_id)
    if not ds:
        raise toolkit.ObjectNotFound("Dataset not found")

    toolkit.check_access("dataset_show", context, data_dict)

    result = ds.as_dict()
    # Enrich stations with full data
    assocs = station_db.HydroDatasetStation.get_by_dataset(ds.id)
    stations = []
    for assoc in assocs:
        st = station_db.HydroStation.get(id=assoc.station_id)
        if st:
            stations.append(st.as_dict())
    result["stations_detail"] = stations
    return result


def dataset_update(context, data_dict):
    """Update an existing dataset.

    :param id: Dataset UUID (required)
    :param station_ids: Updated list of station IDs
    :returns: Updated dataset dict
    """
    ds_id = data_dict.get("id")
    if not ds_id:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    ds = station_db.HydroDataset.get(id=ds_id)
    if not ds:
        ds = station_db.HydroDataset.get(name=ds_id)
    if not ds:
        raise toolkit.ObjectNotFound("Dataset not found")

    toolkit.check_access("dataset_update", context, {"id": ds.id})

    from ckanext.stationsdischarge.logic.schema import dataset_update_schema
    ctx = dict(context, dataset_id=ds.id)
    data, errors = _validate_data(data_dict, dataset_update_schema(), ctx)
    if errors:
        raise toolkit.ValidationError(errors)

    updatable = ("title", "name", "description", "owner_org",
                 "time_range", "agg", "interval_ms", "export_format")
    for field in updatable:
        if field == "interval_ms" and "interval_ms" in data_dict:
            ds.interval_ms = data.get("interval_ms")
            continue
        if field in data and data[field] is not None:
            setattr(ds, field, data[field])

    ds.modified = datetime.datetime.utcnow()

    if "station_ids" in data_dict:
        station_ids = data_dict["station_ids"]
        if isinstance(station_ids, str):
            station_ids = [s.strip() for s in station_ids.split(",") if s.strip()]
        _save_dataset_stations(ds.id, station_ids)

    model.Session.commit()
    return ds.as_dict()


def dataset_delete(context, data_dict):
    """Delete a dataset.

    :param id: Dataset UUID (required)
    """
    ds_id = data_dict.get("id")
    if not ds_id:
        raise toolkit.ValidationError({"id": ["Missing value"]})

    ds = station_db.HydroDataset.get(id=ds_id)
    if not ds:
        ds = station_db.HydroDataset.get(name=ds_id)
    if not ds:
        raise toolkit.ObjectNotFound("Dataset not found")

    toolkit.check_access("dataset_delete", context, {"id": ds.id})

    station_db.HydroDatasetStation.delete_by_dataset(ds.id)
    model.Session.delete(ds)
    model.Session.commit()
    return {"success": True}


def dataset_list(context, data_dict):
    """List datasets with optional filtering.

    :param owner_org: Filter by organization (optional)
    :param q: Search query (optional)
    :param limit: Max results (default 100)
    :param offset: Offset for pagination (default 0)
    :returns: Dict with results and count
    """
    toolkit.check_access("dataset_list", context, data_dict)

    try:
        limit = int(data_dict.get("limit", 100))
    except (ValueError, TypeError):
        limit = 100
    try:
        offset = int(data_dict.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0

    results, total = station_db.HydroDataset.list_datasets(
        owner_org=data_dict.get("owner_org"),
        q=data_dict.get("q"),
        limit=limit,
        offset=offset,
    )

    return {
        "count": total,
        "results": [ds.as_dict() for ds in results],
    }


def dataset_geojson(context, data_dict):
    """Return a dataset's stations as a GeoJSON FeatureCollection.

    :param id: Dataset UUID or name (required)
    :param include_telemetry: Include latest telemetry (optional)
    :returns: GeoJSON FeatureCollection
    """
    ds_data = dataset_show(context, data_dict)
    toolkit.check_access("dataset_geojson", context, data_dict)

    include_telemetry = str(data_dict.get("include_telemetry", "")).lower() == "true"
    tb_url, tb_api_key = None, None
    if include_telemetry:
        tb_url, tb_api_key = _get_tb_config()

    features = []
    for station_dict in ds_data.get("stations_detail", []):
        lat = station_dict.get("latitude")
        lon = station_dict.get("longitude")
        if lat is None or lon is None:
            continue

        props = {
            "id": station_dict["id"],
            "title": station_dict["title"],
            "name": station_dict["name"],
            "station_id": station_dict["station_id"],
            "station_status": station_dict.get("station_status"),
            "river_name": station_dict.get("river_name"),
            "basin_name": station_dict.get("basin_name"),
            "country": station_dict.get("country"),
            "elevation_masl": station_dict.get("elevation_masl"),
        }

        if include_telemetry and tb_api_key:
            entity_id = station_dict.get("thingsboard_entity_id")
            keys_list = station_dict.get("telemetry_keys", [])
            tel_keys = ",".join(k["telemetry_key"] for k in keys_list)
            if entity_id and tel_keys:
                try:
                    tel = _fetch_telemetry(tb_url, tb_api_key, entity_id, tel_keys, limit=1)
                    latest = {}
                    for k, v in tel.items():
                        if v:
                            latest[k] = {"value": float(v[0].get("value", 0)), "ts": v[0].get("ts")}
                    if latest:
                        props["telemetry"] = latest
                except Exception as e:
                    log.debug("Dataset GeoJSON: skipping telemetry for %s: %s",
                              station_dict.get("name"), e)

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "dataset": {
            "id": ds_data["id"],
            "title": ds_data["title"],
            "name": ds_data["name"],
        },
    }


def dataset_csv(context, data_dict):
    """Return a dataset's stations as CSV data.

    :param id: Dataset UUID or name (required)
    :param include_telemetry: Include latest telemetry (optional)
    :returns: Dict with csv_content string
    """
    ds_data = dataset_show(context, data_dict)
    toolkit.check_access("dataset_csv", context, data_dict)

    include_telemetry = str(data_dict.get("include_telemetry", "")).lower() == "true"
    tb_url, tb_api_key = None, None
    if include_telemetry:
        tb_url, tb_api_key = _get_tb_config()

    import csv
    import io
    output = io.StringIO()

    base_headers = [
        "station_id", "title", "name", "latitude", "longitude",
        "station_status", "river_name", "basin_name", "country",
        "elevation_masl",
    ]

    all_tel_keys = set()
    stations_with_tel = []
    for station_dict in ds_data.get("stations_detail", []):
        tel_data = {}
        if include_telemetry and tb_api_key:
            entity_id = station_dict.get("thingsboard_entity_id")
            keys_list = station_dict.get("telemetry_keys", [])
            tel_keys = ",".join(k["telemetry_key"] for k in keys_list)
            if entity_id and tel_keys:
                try:
                    tel = _fetch_telemetry(tb_url, tb_api_key, entity_id, tel_keys, limit=1)
                    for k, v in tel.items():
                        if v:
                            tel_data[k] = v[0].get("value", "")
                            all_tel_keys.add(k)
                except Exception:
                    pass
        stations_with_tel.append((station_dict, tel_data))

    tel_headers = sorted(all_tel_keys)
    headers = base_headers + tel_headers

    writer = csv.writer(output)
    writer.writerow(headers)

    for station_dict, tel_data in stations_with_tel:
        row = [station_dict.get(h, "") for h in base_headers]
        for tk in tel_headers:
            row.append(tel_data.get(tk, ""))
        writer.writerow(row)

    return {
        "csv_content": output.getvalue(),
        "dataset": {
            "id": ds_data["id"],
            "title": ds_data["title"],
            "name": ds_data["name"],
        },
    }
