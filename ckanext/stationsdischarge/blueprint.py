"""Flask Blueprint with routes for hydro station management."""

import logging

from flask import Blueprint
import ckan.model as model
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as h

from ckanext.stationsdischarge import db as station_db

log = logging.getLogger(__name__)

hydro_stations = Blueprint(
    "hydro_stations",
    __name__,
    url_prefix="/hydro-station",
    template_folder="templates",
)


def _get_context():
    return {
        "model": model,
        "session": model.Session,
        "user": toolkit.g.user,
    }


def _get_organizations():
    """Return list of organizations the current user can create stations in."""
    try:
        context = _get_context()
        orgs = toolkit.get_action("organization_list_for_user")(
            context, {"permission": "create_dataset"}
        )
        return orgs
    except Exception:
        return []


# ── LIST ─────────────────────────────────────────────

@hydro_stations.route("/", methods=["GET"])
def index():
    context = _get_context()
    try:
        data_dict = {
            "q": toolkit.request.args.get("q", ""),
            "station_status": toolkit.request.args.get("station_status", ""),
            "submission_status": toolkit.request.args.get("submission_status", ""),
            "org_id": toolkit.request.args.get("org_id", ""),
            "order_by": toolkit.request.args.get("order_by", "modified"),
            "limit": toolkit.request.args.get("limit", "50"),
            "offset": toolkit.request.args.get("offset", "0"),
        }
        result = toolkit.get_action("station_list")(context, data_dict)
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized")
    except Exception as e:
        log.error("Error listing stations: %s", e)
        result = {"results": [], "count": 0}

    extra_vars = {
        "stations": result["results"],
        "count": result["count"],
        "q": data_dict["q"],
        "station_status": data_dict["station_status"],
        "submission_status": data_dict["submission_status"],
        "org_id": data_dict["org_id"],
        "organizations": _get_organizations(),
    }
    return toolkit.render("stationsdischarge/index.html", extra_vars=extra_vars)


# ── NEW / CREATE ─────────────────────────────────────

@hydro_stations.route("/new", methods=["GET", "POST"])
def new():
    context = _get_context()

    try:
        toolkit.check_access("station_create", context, {})
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized to create stations")

    errors = {}
    error_summary = {}
    data = {}

    if toolkit.request.method == "POST":
        data = dict(toolkit.request.form)

        # Handle submission action
        submission_action = data.pop("submission_action", "draft")
        data["submission_status"] = "draft"
        if submission_action == "submit":
            data["submission_status"] = "pending"

        try:
            station = toolkit.get_action("station_create")(context, data)
            h.flash_success("Station created successfully.")
            return h.redirect_to("hydro_stations.show", name=station["name"])
        except toolkit.ValidationError as e:
            errors = e.error_dict or {}
            error_summary = _format_error_summary(errors)
        except toolkit.NotAuthorized:
            toolkit.abort(403, "Not authorized")

    extra_vars = {
        "data": data,
        "errors": errors,
        "error_summary": error_summary,
        "organizations": _get_organizations(),
        "form_action": toolkit.url_for("hydro_stations.new"),
        "is_edit": False,
    }
    return toolkit.render("stationsdischarge/edit_base.html", extra_vars=extra_vars)


# ── SHOW ─────────────────────────────────────────────

@hydro_stations.route("/<name>", methods=["GET"])
def show(name):
    context = _get_context()

    try:
        station = toolkit.get_action("station_show")(context, {"id": name})
    except toolkit.ObjectNotFound:
        toolkit.abort(404, "Station not found")
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized to view this station")

    # Fetch organization info
    org = None
    if station.get("owner_org"):
        try:
            org = toolkit.get_action("organization_show")(
                context, {"id": station["owner_org"]}
            )
        except Exception:
            pass

    # Fetch creator info
    creator = None
    if station.get("user_id"):
        try:
            creator = model.User.get(station["user_id"])
        except Exception:
            pass

    extra_vars = {
        "station": station,
        "org": org,
        "creator": creator,
    }
    return toolkit.render("stationsdischarge/read.html", extra_vars=extra_vars)


# ── EDIT / UPDATE ────────────────────────────────────

@hydro_stations.route("/<name>/edit", methods=["GET", "POST"])
def edit(name):
    context = _get_context()

    try:
        station = toolkit.get_action("station_show")(context, {"id": name})
    except toolkit.ObjectNotFound:
        toolkit.abort(404, "Station not found")
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized")

    try:
        toolkit.check_access("station_update", context, {"id": station["id"]})
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized to edit this station")

    errors = {}
    error_summary = {}
    data = station

    if toolkit.request.method == "POST":
        data = dict(toolkit.request.form)
        data["id"] = station["id"]

        # Handle submission action
        submission_action = data.pop("submission_action", None)
        if submission_action:
            data["submission_action"] = submission_action

        try:
            updated = toolkit.get_action("station_update")(context, data)
            h.flash_success("Station updated successfully.")
            return h.redirect_to("hydro_stations.show", name=updated["name"])
        except toolkit.ValidationError as e:
            errors = e.error_dict or {}
            error_summary = _format_error_summary(errors)
        except toolkit.NotAuthorized:
            toolkit.abort(403, "Not authorized")

    extra_vars = {
        "data": data,
        "errors": errors,
        "error_summary": error_summary,
        "organizations": _get_organizations(),
        "form_action": toolkit.url_for("hydro_stations.edit", name=name),
        "is_edit": True,
    }
    return toolkit.render("stationsdischarge/edit_base.html", extra_vars=extra_vars)


# ── DELETE ───────────────────────────────────────────

@hydro_stations.route("/<name>/delete", methods=["GET", "POST"])
def delete(name):
    context = _get_context()

    try:
        station = toolkit.get_action("station_show")(context, {"id": name})
    except toolkit.ObjectNotFound:
        toolkit.abort(404, "Station not found")
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Not authorized")

    try:
        toolkit.check_access("station_delete", context, {"id": station["id"]})
    except toolkit.NotAuthorized:
        toolkit.abort(403, "Only sysadmins can delete stations")

    if toolkit.request.method == "POST":
        try:
            toolkit.get_action("station_delete")(context, {"id": station["id"]})
            h.flash_success(f"Station '{station['title']}' deleted.")
            return h.redirect_to("hydro_stations.index")
        except Exception as e:
            h.flash_error(f"Error deleting station: {e}")
            return h.redirect_to("hydro_stations.show", name=name)

    extra_vars = {"station": station}
    return toolkit.render("stationsdischarge/confirm_delete.html", extra_vars=extra_vars)


# ── HELPERS ──────────────────────────────────────────

def _format_error_summary(errors):
    """Convert error dict to summary for display."""
    summary = {}
    for field, msgs in errors.items():
        if isinstance(msgs, list):
            summary[field] = "; ".join(msgs)
        else:
            summary[field] = str(msgs)
    return summary
