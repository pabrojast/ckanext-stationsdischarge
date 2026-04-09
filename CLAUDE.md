# CKAN Extension Guidelines

## Architecture

This extension (`ckanext-stationsdischarge`) provides:
- **YAML schema** (`schemas/hydro_station.yaml`) for a custom `hydro_station` dataset type compatible with ckanext-schemingdcat
- **Python plugin** with custom validators (`valid_latitude`, `valid_longitude`, `valid_uuid`, `valid_curve_params_json`), auto-generation of `spatial` GeoJSON from lat/lon, and template helpers
- **Documentation** for API usage by the external rating-service microservice

## Key Files

| File | Purpose |
|------|---------|
| `ckanext/stationsdischarge/schemas/hydro_station.yaml` | schemingdcat YAML schema |
| `ckanext/stationsdischarge/plugin.py` | Main plugin class (IConfigurer, IValidators, IPackageController, ITemplateHelpers) |
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
- ckanext-schemingdcat
- ckanext-spatial (for spatial indexing)
