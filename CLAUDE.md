# CKAN Extension Guidelines

## Architecture

This extension (`ckanext-stationsdischarge`) provides standalone hydrometric station management pages for CKAN, following the ckanext-pages pattern (own DB table, Flask Blueprint routes, custom HTML forms). **No dependency on ckanext-scheming or ckanext-schemingdcat.**

- **SQLAlchemy model** (`db.py`) with `hydro_stations` table (30+ columns)
- **Flask Blueprint** (`blueprint.py`) with routes under `/hydro-station`
- **CKAN Actions** (`actions.py`) for CRUD: `station_create`, `station_show`, `station_update`, `station_delete`, `station_list`
- **Auth functions** (`auth.py`) with org membership checks and approval workflow
- **Custom validators** (`validators.py`): `valid_latitude`, `valid_longitude`, `valid_uuid`, `valid_curve_params_json`
- **Template helpers** (`helpers.py`) for labels, badges, and curve formatting
- **Auto-generation of spatial GeoJSON** from lat/lon coordinates

## Key Files

| File | Purpose |
|------|---------|
| `ckanext/stationsdischarge/plugin.py` | Main plugin (IConfigurer, IConfigurable, IBlueprint, IActions, IAuthFunctions, ITemplateHelpers) |
| `ckanext/stationsdischarge/db.py` | SQLAlchemy model HydroStation with BaseModel declarative pattern |
| `ckanext/stationsdischarge/blueprint.py` | Flask Blueprint with 6 routes (index, new, show, edit, delete) |
| `ckanext/stationsdischarge/actions.py` | 5 CKAN actions for station CRUD + list |
| `ckanext/stationsdischarge/auth.py` | Authorization functions with org membership checks |
| `ckanext/stationsdischarge/helpers.py` | Template helpers (10 functions) |
| `ckanext/stationsdischarge/logic/schema.py` | Validation schemas for create/update |
| `ckanext/stationsdischarge/validators.py` | Custom validator functions |
| `docs/api-usage.md` | API documentation for rating-service |
| `docs/examples.json` | Example station datasets (3 curve types) |
| `docs/deployment.md` | Deployment instructions for Docker/Kubernetes |

## Testing

```bash
cd /path/to/ckanext-stationsdischarge
python -m pytest tests/ -v
```

## Dependencies

- CKAN 2.10+
- No external extension dependencies (scheming/schemingdcat NOT required)
