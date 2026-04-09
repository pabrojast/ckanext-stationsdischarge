import json
import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.stationsdischarge import validators as v

log = logging.getLogger(__name__)


class StationsDischargePlugin(plugins.SingletonPlugin):
    """Thin CKAN extension for hydrometric-station extras.

    Responsibilities
    ----------------
    * Register custom validators used by the hydro_station scheming YAML.
    * Auto-generate the ``spatial`` GeoJSON field from latitude/longitude
      on create/update so that ckanext-spatial indexes the station.
    * Provide template helpers for the station detail page.

    The heavy lifting (form rendering, API) is handled by
    ckanext-schemingdcat via the YAML schema.
    """

    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IValidators)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.ITemplateHelpers)

    # ── IConfigurer ─────────────────────────────────

    def update_config(self, config):
        toolkit.add_template_directory(config, "templates")
        toolkit.add_public_directory(config, "public")

    # ── IValidators ─────────────────────────────────

    def get_validators(self):
        return {
            "valid_latitude": v.valid_latitude,
            "valid_longitude": v.valid_longitude,
            "valid_uuid": v.valid_uuid,
            "valid_curve_params_json": v.valid_curve_params_json,
        }

    # ── IPackageController ──────────────────────────

    def before_dataset_index(self, data_dict):
        """Ensure station_id is indexed as a Solr string field."""
        return data_dict

    def create(self, entity):
        """After-create: auto-generate spatial from lat/lon."""
        self._auto_spatial(entity)

    def edit(self, entity):
        """After-edit: auto-generate spatial from lat/lon."""
        self._auto_spatial(entity)

    @staticmethod
    def _auto_spatial(entity):
        """Build a GeoJSON Point from latitude/longitude extras.

        Only touches datasets of type ``hydro_station`` and only when
        the ``spatial`` field is empty.
        """
        if not hasattr(entity, "type") or entity.type != "hydro_station":
            return

        extras = {e["key"]: e["value"] for e in (entity.extras or [])}
        lat = extras.get("latitude")
        lon = extras.get("longitude")

        if not lat or not lon:
            return

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (ValueError, TypeError):
            return

        current_spatial = extras.get("spatial", "").strip()
        if current_spatial:
            return

        geojson = json.dumps(
            {"type": "Point", "coordinates": [lon_f, lat_f]}
        )

        # Update extras list
        found = False
        for e in entity.extras:
            if e["key"] == "spatial":
                e["value"] = geojson
                found = True
                break
        if not found:
            entity.extras.append({"key": "spatial", "value": geojson})

        log.info(
            "stationsdischarge: auto-generated spatial for %s (%s, %s)",
            entity.name,
            lat,
            lon,
        )

    # ── ITemplateHelpers ────────────────────────────

    def get_helpers(self):
        return {
            "stationsdischarge_parse_curve_params": _parse_curve_params,
            "stationsdischarge_format_curve_summary": _format_curve_summary,
        }


# ── Helper functions ────────────────────────────────


def _parse_curve_params(json_str):
    """Safely parse curve_params_json, returning dict or None."""
    if not json_str:
        return None
    try:
        return json.loads(json_str) if isinstance(json_str, str) else json_str
    except (json.JSONDecodeError, TypeError):
        return None


def _format_curve_summary(curve_type, json_str):
    """Return a human-readable one-line summary of the rating curve."""
    params = _parse_curve_params(json_str)
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

    return curve_type
