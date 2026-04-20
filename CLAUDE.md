# CKAN Extension Guidelines

## Architecture

This extension (`ckanext-stationsdischarge`) provides standalone hydrometric station management pages for CKAN, following the ckanext-pages pattern (own DB tables, Flask Blueprint routes, custom HTML forms). **No dependency on ckanext-scheming or ckanext-schemingdcat.**

- **SQLAlchemy models** (`db.py`) with 4 tables: `hydro_stations`, `station_telemetry_keys`, `hydro_datasets`, `hydro_dataset_stations`
- **Two Flask Blueprints** (`blueprint.py`): `hydro_stations` under `/hydro-station`, `hydro_datasets` under `/hydro-dataset`
- **CKAN Actions** (`actions.py`) for station CRUD, telemetry, GeoJSON, ThingsBoard metadata fetch, and dataset CRUD with GeoJSON/CSV export
- **Auth functions** (`auth.py`) with org membership checks and approval workflow
- **Custom validators** (`validators.py`): `valid_latitude`, `valid_longitude`, `valid_uuid`
- **Template helpers** (`helpers.py`) for labels, badges, and status display
- **Auto-generation of spatial GeoJSON** from lat/lon coordinates
- **ThingsBoard integration** for auto-fetching device metadata and telemetry keys
- **Multi-key telemetry** support: each station can have multiple telemetry keys with metadata (key, label, unit, variable_type)
- **Dataset grouping**: stations can be grouped into datasets for batch GeoJSON/CSV export with time range and aggregation settings

## Key Files

| File | Purpose |
|------|---------|
| `ckanext/stationsdischarge/plugin.py` | Main plugin (IConfigurer, IConfigurable, IBlueprint, IActions, IAuthFunctions, ITemplateHelpers) |
| `ckanext/stationsdischarge/db.py` | SQLAlchemy models: HydroStation, StationTelemetryKey, HydroDataset, HydroDatasetStation |
| `ckanext/stationsdischarge/blueprint.py` | Two Flask Blueprints: `hydro_stations` (10 routes) + `hydro_datasets` (7 routes) |
| `ckanext/stationsdischarge/actions.py` | 15 CKAN actions: station CRUD + telemetry + geojson + TB fetch + dataset CRUD + dataset export |
| `ckanext/stationsdischarge/auth.py` | Authorization functions for stations (7) and datasets (7) |
| `ckanext/stationsdischarge/helpers.py` | Template helpers for status labels, badges |
| `ckanext/stationsdischarge/logic/schema.py` | Validation schemas for station and dataset create/update |
| `ckanext/stationsdischarge/validators.py` | Custom validator functions (latitude, longitude, UUID) |
| `docs/api-usage.md` | API documentation for all endpoints |
| `docs/examples.json` | Example station data with multi-key telemetry |
| `docs/deployment.md` | Deployment instructions for Docker/Kubernetes |

## Testing

```bash
cd /path/to/ckanext-stationsdischarge
python -m pytest tests/ -v
```

## Dependencies

- CKAN 2.10+
- No external extension dependencies (scheming/schemingdcat NOT required)
- ThingsBoard instance (optional, for metadata auto-fetch): configure via `CKANEXT__STATIONSDISCHARGE__TB_URL` and `CKANEXT__STATIONSDISCHARGE__TB_API_KEY` env vars
