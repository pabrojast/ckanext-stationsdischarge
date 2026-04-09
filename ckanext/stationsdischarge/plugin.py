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
        from ckanext.stationsdischarge.db import init_db
        init_db()

    # ── IBlueprint ──────────────────────────────────

    def get_blueprint(self):
        from ckanext.stationsdischarge.blueprint import hydro_stations
        return [hydro_stations]

    # ── IActions ────────────────────────────────────

    def get_actions(self):
        from ckanext.stationsdischarge import actions
        return {
            "station_create": actions.station_create,
            "station_show": actions.station_show,
            "station_update": actions.station_update,
            "station_delete": actions.station_delete,
            "station_list": actions.station_list,
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
        }

    # ── ITemplateHelpers ────────────────────────────

    def get_helpers(self):
        return station_helpers.get_helpers()
