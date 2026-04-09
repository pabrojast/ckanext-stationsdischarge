import json
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


# ── Rating-curve parameters ─────────────────────────

_VALID_CURVE_TYPES = {"power", "linear_segments", "table_interpolation"}


def valid_curve_params_json(key, data, errors, context):
    """Cross-field validator: validates curve_params_json against curve_type.

    Registered as a dataset-level validator via scheming's
    ``dataset_validators`` or called from IValidators.
    When used as a simple single-field validator it only checks valid JSON.
    """
    value = data.get(key)
    if not value:
        return

    # Parse JSON
    try:
        params = json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError) as exc:
        errors[key].append(f"Invalid JSON: {exc}")
        return

    if not isinstance(params, dict):
        errors[key].append("Must be a JSON object ({...}).")
        return

    # Try to find curve_type in sibling fields
    curve_type_key = None
    for k in data:
        if isinstance(k, tuple) and k[-1] == "curve_type":
            curve_type_key = k
            break
    if not curve_type_key:
        # standalone validation – just accept valid JSON
        return

    curve_type = data.get(curve_type_key, "")

    if curve_type == "power":
        for field in ("a", "b", "h0"):
            if field not in params:
                errors[key].append(
                    f'Power curve requires "{field}" '
                    f'(e.g. {{"a": 2.5, "b": 1.8, "h0": 0.15}}).'
                )
                return
            try:
                float(params[field])
            except (ValueError, TypeError):
                errors[key].append(f'"{field}" must be a number.')
                return

    elif curve_type == "linear_segments":
        segments = params.get("segments")
        if not isinstance(segments, list) or len(segments) == 0:
            errors[key].append(
                'Linear segments requires "segments" as a non-empty list '
                '(e.g. [{"h_min":0, "h_max":1, "slope":2.5, "intercept":0}]).'
            )
            return
        for i, seg in enumerate(segments):
            for field in ("h_min", "h_max", "slope", "intercept"):
                if field not in seg:
                    errors[key].append(
                        f'Segment {i} is missing "{field}".'
                    )
                    return

    elif curve_type == "table_interpolation":
        table = params.get("table")
        if not isinstance(table, list) or len(table) < 2:
            errors[key].append(
                'Table interpolation requires "table" with at least 2 rows '
                '(e.g. [{"h":0, "q":0}, {"h":0.5, "q":1.2}]).'
            )
            return
        for i, row in enumerate(table):
            if "h" not in row or "q" not in row:
                errors[key].append(
                    f'Row {i} must have "h" and "q" keys.'
                )
                return

    # Re-serialize to ensure consistent storage
    data[key] = json.dumps(params, ensure_ascii=False)
