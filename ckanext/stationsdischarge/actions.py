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

    keys_list is a list of dicts with: telemetry_key, label, unit, variable_type,
    sort_order, calibration_offset.
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
        raw_offset = key_data.get("calibration_offset")
        raw_slope = key_data.get("calibration_slope")
        try:
            tk.calibration_offset = float(raw_offset) if raw_offset not in (None, "") else 0.0
        except (TypeError, ValueError):
            tk.calibration_offset = 0.0
        try:
            tk.calibration_slope = float(raw_slope) if raw_slope not in (None, "") else 1.0
        except (TypeError, ValueError):
            tk.calibration_slope = 1.0
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        log.error("ThingsBoard API error %s: %s", e.code, body)
        error_msg = "ThingsBoard API returned HTTP %s" % e.code
        if body:
            try:
                tb_error = json.loads(body)
                if isinstance(tb_error, dict):
                    error_msg += ": " + tb_error.get("message", body[:200])
                elif isinstance(tb_error, str):
                    error_msg += ": " + tb_error[:200]
                else:
                    error_msg += ": " + body[:200]
            except (json.JSONDecodeError, ValueError):
                error_msg += ": " + body[:200]
        raise toolkit.ValidationError(
            {"thingsboard": [error_msg]}
        )
    except urllib.error.URLError as e:
        log.error("ThingsBoard connection error: %s", e.reason)
        raise toolkit.ValidationError(
            {"thingsboard": ["Cannot connect to ThingsBoard: %s" % e.reason]}
        )


def _apply_calibration(telemetry, calibrations):
    """Apply per-key linear calibration to a TB telemetry response in-place.

    *telemetry* is the ``{key: [{ts, value}, ...]}`` shape returned by
    ThingsBoard. *calibrations* maps telemetry key → ``(slope, offset)``
    where the displayed value becomes ``slope * raw + offset``. Non-numeric
    values pass through untouched. Pass-through entries (slope=1, offset=0)
    are skipped to avoid float drift.
    """
    if not telemetry or not isinstance(telemetry, dict) or not calibrations:
        return telemetry
    for key, points in telemetry.items():
        cal = calibrations.get(key)
        if not cal or not points:
            continue
        slope, offset = cal
        if slope in (1, 1.0) and not offset:
            continue
        for pt in points:
            raw = pt.get("value")
            try:
                pt["value"] = float(slope) * float(raw) + float(offset)
            except (TypeError, ValueError):
                continue
    return telemetry


def _telemetry_key_calibrations(keys_iterable, attr_lookup="attribute"):
    """Build the calibrations map ``_apply_calibration`` expects.

    *keys_iterable* may yield either ``StationTelemetryKey`` ORM rows or the
    dict form coming out of ``as_dict()``. We accept both because dataset
    GeoJSON enrichment goes through the dict form while ``station_telemetry``
    has ORM rows directly available.
    """
    cals = {}
    for tk in keys_iterable or []:
        if hasattr(tk, "telemetry_key"):
            k = tk.telemetry_key
            slope = tk.calibration_slope if tk.calibration_slope is not None else 1.0
            offset = tk.calibration_offset if tk.calibration_offset is not None else 0.0
        else:
            k = tk.get("telemetry_key")
            slope = tk.get("calibration_slope")
            offset = tk.get("calibration_offset")
            slope = 1.0 if slope in (None, "") else slope
            offset = 0.0 if offset in (None, "") else offset
        if k and ((slope not in (1, 1.0)) or offset):
            cals[k] = (slope, offset)
    return cals


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
                # orderBy=DESC ensures we get the most recent `limit` points
                # within the range, not the oldest. Without it, some TB
                # versions return data ascending from startTs and silently
                # truncate the newest values.
                return (
                    "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
                    "?keys=%s&startTs=%s&endTs=%s&limit=%s&orderBy=DESC"
                    % (safe_id, safe_keys, str(start_ts), str(end_ts), limit)
                )
        else:
            return (
                "/api/plugins/telemetry/DEVICE/%s/values/timeseries"
                "?keys=%s&orderBy=DESC" % (safe_id, safe_keys)
            )

    # ── Attempt 1: with aggregation (if requested) ──
    agg_error = None
    if agg and interval and start_ts and end_ts:
        api_path = _build_url(use_agg=True)
        log.debug("Fetching telemetry WITH aggregation: keys=%s agg=%s interval=%s",
                  keys, agg, interval)
        try:
            return _tb_request(tb_url, tb_api_key, api_path)
        except toolkit.ValidationError as e:
            agg_error = e
            err_parts = e.error_dict.get("thingsboard", ["unknown error"]) if hasattr(e, 'error_dict') else [str(e)]
            log.warning(
                "Aggregated telemetry failed for %s (will retry raw): %s",
                entity_id, err_parts[0] if err_parts else str(e)
            )

    # ── Attempt 2: raw data without aggregation ──
    api_path = _build_url(use_agg=False)
    log.debug("Fetching telemetry WITHOUT aggregation: keys=%s limit=%s", keys, limit)
    try:
        return _tb_request(tb_url, tb_api_key, api_path)
    except toolkit.ValidationError as raw_err:
        # If raw also fails, raise the aggregation error (more informative)
        # unless there was no aggregation attempt
        if agg_error is not None:
            raise agg_error
        raise raw_err


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

    # ThingsBoard stores linear calibration as device-level SERVER_SCOPE
    # attributes (`slope`, `intercept`). Surface them as a dedicated block so
    # the form can pre-fill the matching telemetry key without the JS having
    # to know the convention.
    calibration = {}
    for src, dst in (("slope", "slope"), ("intercept", "offset")):
        if src in attributes:
            try:
                calibration[dst] = float(attributes[src])
            except (TypeError, ValueError):
                pass

    return {
        "device": device_info,
        "attributes": attributes,
        "telemetry_keys": telemetry_keys,
        "calibration": calibration,
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

    keys = data_dict.get("keys")
    if not keys:
        keys_list = station_db.StationTelemetryKey.get_by_station(station.id)
        keys = ",".join(k.telemetry_key for k in keys_list) if keys_list else ""

    # If the station has nothing to query, return an empty result instead of
    # a 400. Dashboards then render an empty-state instead of an error toast.
    if not entity_id or not keys:
        return {
            "station_id": station.station_id,
            "station_name": station.name,
            "thingsboard_entity_id": entity_id,
            "telemetry_keys": keys,
            "telemetry": {},
            "warning": (
                "Station has no ThingsBoard entity configured"
                if not entity_id else
                "Station has no telemetry keys configured"
            ),
        }

    tr = _resolve_time_range(data_dict)

    telemetry_raw = _fetch_telemetry(
        tb_url, tb_api_key, entity_id, keys,
        start_ts=tr["start_ts"],
        end_ts=tr["end_ts"],
        limit=tr["limit"],
        agg=tr["agg"],
        interval=tr["interval"],
    )

    cals = _telemetry_key_calibrations(
        station_db.StationTelemetryKey.get_by_station(station.id)
    )
    telemetry_raw = _apply_calibration(telemetry_raw, cals)

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
                    tel = _apply_calibration(
                        tel, _telemetry_key_calibrations(keys_list)
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
        time_range=data.get("time_range") or "30d",
        agg=data.get("agg", ""),
        interval_ms=data.get("interval_ms"),
        export_format=data.get("export_format", "geojson"),
        geojson_mode=data.get("geojson_mode") or "compact",
        time_property=data.get("time_property") or "date",
        display_keys=data.get("display_keys") or "",
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
                 "time_range", "agg", "interval_ms", "export_format",
                 "geojson_mode", "time_property", "display_keys")
    for field in updatable:
        if field == "interval_ms" and "interval_ms" in data_dict:
            ds.interval_ms = data.get("interval_ms")
            continue
        if field == "display_keys" and "display_keys" in data_dict:
            # Allow clearing the whitelist by submitting empty value.
            ds.display_keys = data.get("display_keys") or ""
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


def _filter_keys(all_keys_list, whitelist_csv, request_keys_csv):
    """Resolve which telemetry keys to include for a station.

    Precedence: per-request ``keys`` (if provided) overrides the dataset's
    stored ``display_keys`` whitelist. Both are filtered against the keys
    actually configured on the station, so callers can't request keys the
    station does not own.
    """
    station_keys = [k["telemetry_key"] for k in all_keys_list]
    raw = request_keys_csv if request_keys_csv else whitelist_csv
    if not raw:
        return station_keys
    wanted = {s.strip() for s in str(raw).split(",") if s.strip()}
    if not wanted:
        return station_keys
    return [k for k in station_keys if k in wanted]


def _station_base_props(station_dict):
    """Return the static properties shared by every Feature for a station."""
    return {
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


def _fetch_station_telemetry(tb_url, tb_api_key, station_dict, tel_keys, tr):
    """Fetch telemetry from ThingsBoard for a single station, swallowing errors.

    Applies per-key ``calibration_offset`` from the station's telemetry keys
    so dataset GeoJSON consumers (Terria, etc.) see the same calibrated
    values the dashboard does.
    """
    entity_id = station_dict.get("thingsboard_entity_id")
    if not entity_id or not tel_keys:
        return {}
    try:
        tel = _fetch_telemetry(
            tb_url, tb_api_key, entity_id, ",".join(tel_keys),
            start_ts=tr["start_ts"], end_ts=tr["end_ts"], limit=tr["limit"],
            agg=tr["agg"], interval=tr["interval"],
        )
    except Exception as e:
        log.debug("Dataset GeoJSON: skipping telemetry for %s: %s",
                  station_dict.get("name"), e)
        return {}
    return _apply_calibration(
        tel, _telemetry_key_calibrations(station_dict.get("telemetry_keys", []))
    )


def _ts_to_iso(ts_ms):
    """Convert a ThingsBoard millisecond timestamp to ISO 8601 (UTC, with Z)."""
    try:
        ts_int = int(ts_ms)
    except (ValueError, TypeError):
        return None
    return datetime.datetime.utcfromtimestamp(ts_int / 1000.0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _coerce_number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return value


def _build_compact_feature(station_dict, lat, lon, tel, key_meta, allowed_keys):
    """Original 'compact' Feature: one per station with full series + latest."""
    props = _station_base_props(station_dict)
    latest = {}
    series = {}
    for k, points in tel.items():
        if not points or k not in allowed_keys:
            continue
        ordered = sorted(points, key=lambda p: int(p.get("ts", 0)))
        last_val = _coerce_number(ordered[-1].get("value", 0))
        latest[k] = {"value": last_val, "ts": ordered[-1].get("ts")}
        meta = key_meta.get(k, {})
        flat_name = meta.get("label") or k
        if meta.get("unit"):
            flat_name = "%s (%s)" % (flat_name, meta["unit"])
        props[flat_name] = last_val
        compact = []
        for pt in ordered:
            try:
                compact.append([int(pt.get("ts")), float(pt.get("value", 0))])
            except (ValueError, TypeError):
                pass
        if compact:
            series[k] = compact
    if latest:
        props["telemetry"] = latest
    if series:
        props["series"] = series
    return [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        "properties": props,
    }]


def _build_expanded_features(station_dict, lat, lon, tel, key_meta,
                             allowed_keys, time_property):
    """One Feature per (station, timestamp). Powers the Terria time slider.

    Timestamps are unioned across all included keys so missing values at a
    sample don't drop the feature. Each feature carries every key for which a
    value exists at that timestamp under its raw key name (e.g. ``waterLevel``).
    """
    base = _station_base_props(station_dict)
    by_ts = {}
    for k, points in tel.items():
        if not points or k not in allowed_keys:
            continue
        for pt in points:
            ts = pt.get("ts")
            try:
                ts_int = int(ts)
            except (ValueError, TypeError):
                continue
            slot = by_ts.setdefault(ts_int, {})
            slot[k] = _coerce_number(pt.get("value"))

    features = []
    geometry = {"type": "Point", "coordinates": [float(lon), float(lat)]}
    for ts_int in sorted(by_ts.keys()):
        props = dict(base)
        iso = _ts_to_iso(ts_int)
        if not iso:
            continue
        props[time_property] = iso
        props["ts_ms"] = ts_int
        for k, val in by_ts[ts_int].items():
            props[k] = val
            meta = key_meta.get(k, {})
            label = meta.get("label")
            unit = meta.get("unit")
            if label and label != k:
                flat_name = "%s (%s)" % (label, unit) if unit else label
                props[flat_name] = val
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": props,
        })
    return features


def dataset_geojson(context, data_dict):
    """Return a dataset's stations as a GeoJSON FeatureCollection.

    Two output shapes are supported via ``mode`` (or the dataset's stored
    ``geojson_mode``):

    - ``compact`` (default): one Feature per station. Latest values are flat
      properties for pop-ups; the full series is under ``properties.series``.
      This is what the built-in dashboard consumes.
    - ``expanded``: one Feature per (station, timestamp). Drop the URL into
      TerriaJS as a GeoJSON catalog item with ``"timeProperty": "date"`` and
      the time slider scrubs through the values.

    The time window comes from the dataset's stored ``time_range`` /
    ``agg`` / ``interval_ms``, with per-request overrides
    (``time_range``, ``start_ts``, ``end_ts``, ``agg``, ``interval``,
    ``limit``).

    :param id: Dataset UUID or name (required)
    :param include_telemetry: Include telemetry from ThingsBoard ("true"/"false").
        Forced on for ``mode=expanded``.
    :param mode: ``compact`` or ``expanded``
    :param keys: Comma-separated whitelist of telemetry keys (overrides the
        dataset's stored ``display_keys``)
    :param time_range: Override dataset's stored preset (1h/24h/7d/30d/...)
    :param start_ts: Override start timestamp (ms)
    :param end_ts: Override end timestamp (ms)
    :param agg: Override aggregation (AVG/MIN/MAX/SUM/COUNT)
    :param interval: Override aggregation interval (ms)
    :param limit: Max points per key
    :returns: GeoJSON FeatureCollection
    """
    ds_data = dataset_show(context, data_dict)
    toolkit.check_access("dataset_geojson", context, data_dict)

    mode = (data_dict.get("mode") or ds_data.get("geojson_mode") or "compact").lower()
    if mode not in ("compact", "expanded"):
        mode = "compact"

    time_property = (data_dict.get("time_property") or
                     ds_data.get("time_property") or "date")
    keys_override = data_dict.get("keys") or ""
    stored_keys = ds_data.get("display_keys") or ""

    # Expanded mode is meaningless without telemetry — force it on.
    include_telemetry = (
        mode == "expanded"
        or str(data_dict.get("include_telemetry", "")).lower() == "true"
    )

    tr_params = {}
    if include_telemetry:
        tr_params = {
            "time_range": data_dict.get("time_range") or ds_data.get("time_range"),
            "agg": data_dict.get("agg") or ds_data.get("agg"),
            "interval": data_dict.get("interval") or ds_data.get("interval_ms"),
            "start_ts": data_dict.get("start_ts"),
            "end_ts": data_dict.get("end_ts"),
            "limit": data_dict.get("limit"),
        }
    tr = _resolve_time_range(tr_params) if include_telemetry else None

    tb_url, tb_api_key = (None, None)
    if include_telemetry:
        tb_url, tb_api_key = _get_tb_config()

    features = []
    for station_dict in ds_data.get("stations_detail", []):
        lat = station_dict.get("latitude")
        lon = station_dict.get("longitude")
        if lat is None or lon is None:
            continue

        keys_list = station_dict.get("telemetry_keys", [])
        key_meta = {k["telemetry_key"]: k for k in keys_list}
        allowed_keys = _filter_keys(keys_list, stored_keys, keys_override)

        if not include_telemetry or not tb_api_key:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)],
                },
                "properties": _station_base_props(station_dict),
            })
            continue

        tel = _fetch_station_telemetry(
            tb_url, tb_api_key, station_dict, allowed_keys, tr,
        )

        if mode == "expanded":
            features.extend(_build_expanded_features(
                station_dict, lat, lon, tel, key_meta,
                allowed_keys, time_property,
            ))
        else:
            features.extend(_build_compact_feature(
                station_dict, lat, lon, tel, key_meta, allowed_keys,
            ))

    result = {
        "type": "FeatureCollection",
        "features": features,
        "dataset": {
            "id": ds_data["id"],
            "title": ds_data["title"],
            "name": ds_data["name"],
            "mode": mode,
        },
    }
    if mode == "expanded":
        # Hint for TerriaJS catalog config — Terria itself ignores extra
        # top-level keys, so this is purely informational for callers/UI.
        result["terria"] = {
            "type": "geojson",
            "timeProperty": time_property,
        }
    if include_telemetry and tr:
        result["telemetry_window"] = {
            "time_range": tr["time_range"],
            "start_ts": tr["start_ts"],
            "end_ts": tr["end_ts"],
            "agg": tr["agg"],
            "interval_ms": tr["interval"],
            "limit": tr["limit"],
        }
    return result


def dataset_csv(context, data_dict):
    """Return a dataset's stations as Terria-compatible CSV.

    Two shapes via ``mode`` (mirrors the GeoJSON modes):

    - ``snapshot`` (default): one row per station. ``time`` is the timestamp
      of the latest telemetry reading (empty if no telemetry was fetched).
      Each telemetry key becomes its own column with the latest value.
    - ``timeseries``: one row per (station × timestamp). Drop the URL into
      a TerriaJS CSV catalog item and the time slider works out of the box.

    Columns always start with ``lat,lon,time`` (Terria auto-detects these
    names), followed by station metadata and then telemetry key columns.
    Rows missing lat/lon are dropped — Terria cannot render them.

    Time window comes from the dataset's stored ``time_range``/``agg``/
    ``interval_ms``, with the same per-request overrides supported by
    ``dataset_geojson``.

    :param id: Dataset UUID or name (required)
    :param include_telemetry: Include telemetry ("true"/"false").
        Forced on for ``mode=timeseries``.
    :param mode: ``snapshot`` (default) or ``timeseries``
    :param keys: Comma-separated whitelist of telemetry keys
    :param time_range: Override stored preset (1h/24h/7d/30d/...)
    :param start_ts: Override start timestamp (ms)
    :param end_ts: Override end timestamp (ms)
    :param agg: Override aggregation (AVG/MIN/MAX/SUM/COUNT)
    :param interval: Override aggregation interval (ms)
    :param limit: Max points per key
    :returns: Dict with ``csv_content`` string
    """
    ds_data = dataset_show(context, data_dict)
    toolkit.check_access("dataset_csv", context, data_dict)

    mode = (data_dict.get("mode") or "snapshot").lower()
    if mode not in ("snapshot", "timeseries"):
        mode = "snapshot"

    keys_override = data_dict.get("keys") or ""
    stored_keys = ds_data.get("display_keys") or ""

    # timeseries is meaningless without telemetry — force it on.
    include_telemetry = (
        mode == "timeseries"
        or str(data_dict.get("include_telemetry", "")).lower() == "true"
    )

    tr = None
    tb_url, tb_api_key = None, None
    if include_telemetry:
        tr = _resolve_time_range({
            "time_range": data_dict.get("time_range") or ds_data.get("time_range"),
            "agg": data_dict.get("agg") or ds_data.get("agg"),
            "interval": data_dict.get("interval") or ds_data.get("interval_ms"),
            "start_ts": data_dict.get("start_ts"),
            "end_ts": data_dict.get("end_ts"),
            "limit": data_dict.get("limit"),
        })
        tb_url, tb_api_key = _get_tb_config()

    import csv
    import io

    # Terria auto-detects lat/lon/time; keep these three first for clarity.
    base_headers = [
        "lat", "lon", "time",
        "station_id", "title", "name",
        "station_status", "river_name", "basin_name", "country",
        "elevation_masl",
    ]

    # Two passes: first collect rows + the union of telemetry keys actually
    # present, then emit one stable header order.
    rows = []  # list of dicts keyed by header name
    seen_tel_keys = set()

    for station_dict in ds_data.get("stations_detail", []):
        lat = station_dict.get("latitude")
        lon = station_dict.get("longitude")
        if lat is None or lon is None:
            continue  # Terria can't plot without coordinates

        keys_list = station_dict.get("telemetry_keys", [])
        allowed_keys = _filter_keys(keys_list, stored_keys, keys_override)

        base = {
            "lat": lat,
            "lon": lon,
            "station_id": station_dict.get("station_id", ""),
            "title": station_dict.get("title", ""),
            "name": station_dict.get("name", ""),
            "station_status": station_dict.get("station_status", ""),
            "river_name": station_dict.get("river_name", ""),
            "basin_name": station_dict.get("basin_name", ""),
            "country": station_dict.get("country", ""),
            "elevation_masl": station_dict.get("elevation_masl", ""),
        }

        if not include_telemetry or not tb_api_key:
            row = dict(base)
            row["time"] = ""
            rows.append(row)
            continue

        tel = _fetch_station_telemetry(
            tb_url, tb_api_key, station_dict, allowed_keys, tr,
        )

        if mode == "timeseries":
            # One row per (station, ts), unioned across keys so missing samples
            # don't drop the row.
            by_ts = {}
            for k, points in tel.items():
                if not points or k not in allowed_keys:
                    continue
                for pt in points:
                    try:
                        ts_int = int(pt.get("ts"))
                    except (ValueError, TypeError):
                        continue
                    by_ts.setdefault(ts_int, {})[k] = _coerce_number(pt.get("value"))
                    seen_tel_keys.add(k)

            for ts_int in sorted(by_ts.keys()):
                iso = _ts_to_iso(ts_int)
                if not iso:
                    continue
                row = dict(base)
                row["time"] = iso
                for k, v in by_ts[ts_int].items():
                    row[k] = v
                rows.append(row)
        else:
            # snapshot: latest value per key, station time = newest ts seen.
            row = dict(base)
            newest_ts = None
            for k, points in tel.items():
                if not points or k not in allowed_keys:
                    continue
                ordered = sorted(points, key=lambda p: int(p.get("ts", 0)))
                last = ordered[-1]
                row[k] = _coerce_number(last.get("value", ""))
                seen_tel_keys.add(k)
                try:
                    ts_int = int(last.get("ts"))
                except (ValueError, TypeError):
                    ts_int = None
                if ts_int is not None and (newest_ts is None or ts_int > newest_ts):
                    newest_ts = ts_int
            row["time"] = _ts_to_iso(newest_ts) if newest_ts else ""
            rows.append(row)

    tel_headers = sorted(seen_tel_keys)
    headers = base_headers + tel_headers

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if row.get(h) is None else row.get(h) for h in headers])

    result = {
        "csv_content": output.getvalue(),
        "row_count": len(rows),
        "dataset": {
            "id": ds_data["id"],
            "title": ds_data["title"],
            "name": ds_data["name"],
            "mode": mode,
        },
    }
    if include_telemetry and tr:
        result["telemetry_window"] = {
            "time_range": tr["time_range"],
            "start_ts": tr["start_ts"],
            "end_ts": tr["end_ts"],
            "agg": tr["agg"],
            "interval_ms": tr["interval"],
            "limit": tr["limit"],
        }
    return result
