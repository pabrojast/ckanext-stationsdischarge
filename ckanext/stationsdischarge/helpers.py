"""Template helpers for stationsdischarge."""

import json
import logging

log = logging.getLogger(__name__)

# ── Choice labels ──────────────────────────────────────

STATION_STATUS_LABELS = {
    "active": "Active",
    "inactive": "Inactive",
    "maintenance": "Maintenance",
}

OBSERVED_VARIABLE_LABELS = {
    "water_level": "Water Level",
    "precipitation": "Precipitation",
    "discharge": "Discharge",
    "water_temperature": "Water Temperature",
    "sediment_load": "Sediment Load",
    "other": "Other",
}

UNIT_LEVEL_LABELS = {
    "m": "Metres (m)",
    "cm": "Centimetres (cm)",
    "mm": "Millimetres (mm)",
    "ft": "Feet (ft)",
}

UNIT_FLOW_LABELS = {
    "m3/s": "m³/s",
    "l/s": "l/s",
    "ft3/s": "ft³/s",
}

CURVE_TYPE_LABELS = {
    "power": "Power law Q = a·(H − h₀)ᵇ",
    "linear_segments": "Linear segments",
    "table_interpolation": "Table interpolation (H–Q)",
    "piecewise_power": "Piecewise power law",
}

SUBMISSION_STATUS_LABELS = {
    "draft": "Draft",
    "pending": "Pending Review",
    "approved": "Approved",
    "rejected": "Rejected",
}

RESOURCE_TYPE_LABELS = {
    "gauging_report": "Gauging Report",
    "hq_table": "H–Q Table (CSV)",
    "curve_plot": "Rating Curve Plot",
    "photo": "Photo",
    "geojson": "GeoJSON Layer",
    "other": "Other",
}


# ── Helper functions ───────────────────────────────────

def stationsdischarge_parse_curve_params(json_str):
    """Safely parse curve_params_json, returning dict or None."""
    if not json_str:
        return None
    try:
        return json.loads(json_str) if isinstance(json_str, str) else json_str
    except (json.JSONDecodeError, TypeError):
        return None


def stationsdischarge_format_curve_summary(curve_type, json_str):
    """Return a human-readable one-line summary of the rating curve."""
    params = stationsdischarge_parse_curve_params(json_str)
    if not params:
        return "—"

    if curve_type == "power":
        a = params.get("a", "?")
        b = params.get("b", "?")
        h0 = params.get("h0", "?")
        return f"Q = {a}·(H − {h0})^{b}"

    if curve_type == "linear_segments":
        segs = params.get("segments", [])
        return f"{len(segs)} linear segment(s)"

    if curve_type == "table_interpolation":
        table = params.get("table", [])
        return f"{len(table)}-point H–Q table"

    if curve_type == "piecewise_power":
        segs = params.get("segments", [])
        transform = ""
        if "transform_offset" in params or "transform_divisor" in params:
            off = params.get("transform_offset", 0)
            div = params.get("transform_divisor", 1)
            transform = f"H = {off} − raw/{div}, "
        parts = []
        for seg in segs:
            a = seg.get("a", "?")
            b = seg.get("b", "?")
            h_max = seg.get("h_max")
            if h_max is not None:
                parts.append(f"H≤{h_max}: Q={a}·H^{b}")
            else:
                parts.append(f"Q={a}·H^{b}")
        return transform + "; ".join(parts)

    return curve_type


def stationsdischarge_get_label(value, labels_dict):
    """Generic label lookup helper."""
    return labels_dict.get(value, value or "—")


def stationsdischarge_station_status_label(value):
    return stationsdischarge_get_label(value, STATION_STATUS_LABELS)


def stationsdischarge_observed_variable_label(value):
    return stationsdischarge_get_label(value, OBSERVED_VARIABLE_LABELS)


def stationsdischarge_unit_level_label(value):
    return stationsdischarge_get_label(value, UNIT_LEVEL_LABELS)


def stationsdischarge_unit_flow_label(value):
    return stationsdischarge_get_label(value, UNIT_FLOW_LABELS)


def stationsdischarge_curve_type_label(value):
    return stationsdischarge_get_label(value, CURVE_TYPE_LABELS)


def stationsdischarge_submission_status_label(value):
    return stationsdischarge_get_label(value, SUBMISSION_STATUS_LABELS)


def stationsdischarge_submission_badge_class(status):
    """Return CSS class for submission status badge."""
    return {
        "draft": "badge-secondary",
        "pending": "badge-warning",
        "approved": "badge-success",
        "rejected": "badge-danger",
    }.get(status, "badge-secondary")


def stationsdischarge_status_badge_class(status):
    """Return CSS class for station status badge."""
    return {
        "active": "badge-success",
        "inactive": "badge-secondary",
        "maintenance": "badge-warning",
    }.get(status, "badge-secondary")


def get_helpers():
    """Return all template helpers for this extension."""
    return {
        "stationsdischarge_parse_curve_params": stationsdischarge_parse_curve_params,
        "stationsdischarge_format_curve_summary": stationsdischarge_format_curve_summary,
        "stationsdischarge_station_status_label": stationsdischarge_station_status_label,
        "stationsdischarge_observed_variable_label": stationsdischarge_observed_variable_label,
        "stationsdischarge_unit_level_label": stationsdischarge_unit_level_label,
        "stationsdischarge_unit_flow_label": stationsdischarge_unit_flow_label,
        "stationsdischarge_curve_type_label": stationsdischarge_curve_type_label,
        "stationsdischarge_submission_status_label": stationsdischarge_submission_status_label,
        "stationsdischarge_submission_badge_class": stationsdischarge_submission_badge_class,
        "stationsdischarge_status_badge_class": stationsdischarge_status_badge_class,
    }
