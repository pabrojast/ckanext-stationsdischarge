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

SUBMISSION_STATUS_LABELS = {
    "draft": "Draft",
    "pending": "Pending Review",
    "approved": "Approved",
    "rejected": "Rejected",
}


# ── Helper functions ───────────────────────────────────

def stationsdischarge_get_label(value, labels_dict):
    """Generic label lookup helper."""
    return labels_dict.get(value, value or "—")


def stationsdischarge_station_status_label(value):
    return stationsdischarge_get_label(value, STATION_STATUS_LABELS)


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
        "stationsdischarge_station_status_label": stationsdischarge_station_status_label,
        "stationsdischarge_submission_status_label": stationsdischarge_submission_status_label,
        "stationsdischarge_submission_badge_class": stationsdischarge_submission_badge_class,
        "stationsdischarge_status_badge_class": stationsdischarge_status_badge_class,
    }
