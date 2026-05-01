"""Authorization functions for hydro station actions."""

import logging

import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.logic import auth as logic_auth

log = logging.getLogger(__name__)


def _is_sysadmin(context):
    user = context.get("user")
    if not user:
        return False
    user_obj = model.User.get(user)
    return user_obj and user_obj.sysadmin


def _is_org_member(user_name, org_id, role="editor"):
    """Check if user is at least 'role' in the organization."""
    if not user_name or not org_id:
        return False
    try:
        members = toolkit.get_action("member_list")(
            {"ignore_auth": True},
            {"id": org_id, "object_type": "user"},
        )
        user_obj = model.User.get(user_name)
        if not user_obj:
            return False
        role_hierarchy = {"member": 0, "editor": 1, "admin": 2}
        min_level = role_hierarchy.get(role, 1)
        for member_id, _, member_role in members:
            if member_id == user_obj.id:
                if role_hierarchy.get(member_role, 0) >= min_level:
                    return True
        return False
    except Exception:
        return False


@toolkit.auth_allow_anonymous_access
def station_show(context, data_dict):
    """Public for approved stations; author/sysadmin for draft/pending."""
    from ckanext.stationsdischarge.db import HydroStation

    station_id = data_dict.get("id") or data_dict.get("name")
    if not station_id:
        return {"success": True}

    station = HydroStation.get(id=station_id) or HydroStation.get(name=station_id)
    if not station:
        return {"success": True}

    if station.submission_status == "approved":
        return {"success": True}

    if _is_sysadmin(context):
        return {"success": True}

    user = context.get("user")
    if user:
        user_obj = model.User.get(user)
        if user_obj and station.user_id == user_obj.id:
            return {"success": True}
        if _is_org_member(user, station.owner_org, "editor"):
            return {"success": True}

    return {"success": False, "msg": "Not authorized to view this station."}


def station_create(context, data_dict):
    """Organization editors/admins and sysadmins can create stations.
    Only sysadmins can publish directly."""
    if _is_sysadmin(context):
        return {"success": True}

    user = context.get("user")
    if not user:
        return {"success": False, "msg": "Must be logged in to create stations."}

    # Non-sysadmins cannot publish directly
    submission_action = data_dict.get("submission_action")
    if submission_action == "publish":
        return {"success": False, "msg": "Only sysadmins can publish stations directly."}

    org_id = data_dict.get("owner_org")
    if org_id and _is_org_member(user, org_id, "editor"):
        return {"success": True}

    return {"success": False, "msg": "Not authorized to create stations in this organization."}


def station_update(context, data_dict):
    """Author, org admin/editor, or sysadmin can update.
    Only sysadmins can approve or reject."""
    if _is_sysadmin(context):
        return {"success": True}

    # Approval/rejection/publish requires sysadmin
    submission_action = data_dict.get("submission_action")
    if submission_action in ("approve", "reject", "publish"):
        return {"success": False, "msg": "Only sysadmins can approve, reject, or publish stations."}

    user = context.get("user")
    if not user:
        return {"success": False, "msg": "Must be logged in."}

    from ckanext.stationsdischarge.db import HydroStation
    station_id = data_dict.get("id") or data_dict.get("name")
    station = None
    if station_id:
        station = HydroStation.get(id=station_id) or HydroStation.get(name=station_id)

    if station:
        user_obj = model.User.get(user)
        if user_obj and station.user_id == user_obj.id:
            return {"success": True}
        if _is_org_member(user, station.owner_org, "editor"):
            return {"success": True}

    return {"success": False, "msg": "Not authorized to update this station."}


def station_delete(context, data_dict):
    """Only sysadmins can delete stations."""
    if _is_sysadmin(context):
        return {"success": True}
    return {"success": False, "msg": "Only sysadmins can delete stations."}


@toolkit.auth_allow_anonymous_access
def station_list(context, data_dict):
    """Anyone can list stations (privacy is filtered in the action)."""
    return {"success": True}


@toolkit.auth_allow_anonymous_access
def station_telemetry(context, data_dict):
    """Same access rules as station_show — delegates to it."""
    return station_show(context, data_dict)


@toolkit.auth_allow_anonymous_access
def station_geojson(context, data_dict):
    """Anyone can access the GeoJSON endpoint (only approved stations returned)."""
    return {"success": True}


# ── Dataset auth functions ──

def dataset_create(context, data_dict):
    """Organization editors/admins and sysadmins can create datasets."""
    if _is_sysadmin(context):
        return {"success": True}
    user = context.get("user")
    if not user:
        return {"success": False, "msg": "Must be logged in to create datasets."}
    org_id = data_dict.get("owner_org")
    if org_id and _is_org_member(user, org_id, "editor"):
        return {"success": True}
    return {"success": False, "msg": "Not authorized to create datasets in this organization."}


@toolkit.auth_allow_anonymous_access
def dataset_show(context, data_dict):
    """Anyone can view datasets."""
    return {"success": True}


def dataset_update(context, data_dict):
    """Author, org admin/editor, or sysadmin can update."""
    if _is_sysadmin(context):
        return {"success": True}
    user = context.get("user")
    if not user:
        return {"success": False, "msg": "Must be logged in."}
    from ckanext.stationsdischarge.db import HydroDataset
    ds_id = data_dict.get("id") or data_dict.get("name")
    ds = None
    if ds_id:
        ds = HydroDataset.get(id=ds_id) or HydroDataset.get(name=ds_id)
    if ds:
        user_obj = model.User.get(user)
        if user_obj and ds.user_id == user_obj.id:
            return {"success": True}
        if _is_org_member(user, ds.owner_org, "editor"):
            return {"success": True}
    return {"success": False, "msg": "Not authorized to update this dataset."}


def dataset_delete(context, data_dict):
    """Only sysadmins or dataset author can delete."""
    if _is_sysadmin(context):
        return {"success": True}
    user = context.get("user")
    if not user:
        return {"success": False, "msg": "Must be logged in."}
    from ckanext.stationsdischarge.db import HydroDataset
    ds_id = data_dict.get("id") or data_dict.get("name")
    ds = None
    if ds_id:
        ds = HydroDataset.get(id=ds_id) or HydroDataset.get(name=ds_id)
    if ds:
        user_obj = model.User.get(user)
        if user_obj and ds.user_id == user_obj.id:
            return {"success": True}
    return {"success": False, "msg": "Not authorized to delete this dataset."}


@toolkit.auth_allow_anonymous_access
def dataset_list(context, data_dict):
    """Anyone can list datasets."""
    return {"success": True}


@toolkit.auth_allow_anonymous_access
def dataset_geojson(context, data_dict):
    """Anyone can access dataset GeoJSON."""
    return {"success": True}


@toolkit.auth_allow_anonymous_access
def dataset_csv(context, data_dict):
    """Anyone can access dataset CSV."""
    return {"success": True}
