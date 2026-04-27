"""CKAN extension for hydrometric station management.

Standalone implementation (no ckanext-scheming dependency).
Uses its own database table, Flask Blueprint, and CKAN actions/auth.
"""

import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.stationsdischarge import helpers as station_helpers

log = logging.getLogger(__name__)


class StationsDischargePlugin(plugins.SingletonPlugin):
    """Hydrometric station management plugin.

    Provides:
    - Custom DB table ``hydro_stations`` for station data
    - Flask Blueprint with routes for list/create/read/edit/delete
    - CKAN actions for API access (station_create, station_show, etc.)
    - Authorization functions with submission workflow
    - Template helpers for station display
    """

    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.ITemplateHelpers)

    # ── IConfigurer ─────────────────────────────────

    def update_config(self, config):
        toolkit.add_template_directory(config, "templates")
        toolkit.add_public_directory(config, "public")

    # ── IConfigurable ───────────────────────────────

    def configure(self, config):
        """Initialize the hydro_stations table on plugin load."""
        from ckanext.stationsdischarge import db as station_db

        init_db = getattr(station_db, "init_db", None)
        if not callable(init_db):
            raise ImportError(
                "ckanext.stationsdischarge.db does not expose a callable init_db"
            )
        .()

    # ── IBlueprint ──────────────────────────────────

    def get_blueprint(self):
        from ckanext.stationsdischarge.blueprint import hydro_stations, hydro_datasets
        return [hydro_stations, hydro_datasets]

    # ── IActions ────────────────────────────────────

    def get_actions(self):
        from ckanext.stationsdischarge import actions
        return {
            "station_create": actions.station_create,
            "station_show": actions.station_show,
            "station_update": actions.station_update,
            "station_delete": actions.station_delete,
            "station_list": actions.station_list,
            "station_telemetry": actions.station_telemetry,
            "station_geojson": actions.station_geojson,
            "station_fetch_tb_metadata": actions.station_fetch_tb_metadata,
            "dataset_create": actions.dataset_create,
            "dataset_show": actions.dataset_show,
            "dataset_update": actions.dataset_update,
            "dataset_delete": actions.dataset_delete,
            "dataset_list": actions.dataset_list,
            "dataset_geojson": actions.dataset_geojson,
            "dataset_csv": actions.dataset_csv,
        }

    # ── IAuthFunctions ──────────────────────────────

    def get_auth_functions(self):
        from ckanext.stationsdischarge import auth
        return {
            "station_create": auth.station_create,
            "station_show": auth.station_show,
            "station_update": auth.station_update,
            "station_delete": auth.station_delete,
            "station_list": auth.station_list,
            "station_telemetry": auth.station_telemetry,
            "station_geojson": auth.station_geojson,
            "station_fetch_tb_metadata": auth.station_create,
            "dataset_create": auth.dataset_create,
            "dataset_show": auth.dataset_show,
            "dataset_update": auth.dataset_update,
            "dataset_delete": auth.dataset_delete,
            "dataset_list": auth.dataset_list,
            "dataset_geojson": auth.dataset_geojson,
            "dataset_csv": auth.dataset_csv,
        }

    # ── ITemplateHelpers ────────────────────────────

    def get_helpers(self):
        return station_helpers.get_helpers()
