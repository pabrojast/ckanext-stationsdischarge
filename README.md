# ckanext-stationsdischarge

CKAN extension for **hydrometric station management** — ThingsBoard IoT integration and discharge rating curves.

## Overview

This extension turns CKAN into the **source of truth** for hydrometric station configuration. A station is stored as a CKAN dataset of type `hydro_station`, containing:

- Station identification (ID, name, status)
- Geographic location (lat/lon, river, basin)
- ThingsBoard IoT connection (entity ID, device ID, telemetry key)
- Measurement units (level & flow)
- Rating curve definition (power / linear segments / table interpolation)

An external **rating-service** queries CKAN's API to get station metadata, fetches real-time water level from ThingsBoard, applies the rating curve, and delivers discharge values as GeoJSON for TerriaJS.

```
User → CKAN (hydro_station) ← rating-service → ThingsBoard
                                      ↓
                                  TerriaJS (GeoJSON)
```

## Architecture

- **CKAN** stores configuration only — no calculations
- **rating-service** (external microservice) applies the rating curve
- **ThingsBoard** provides real-time telemetry (water level)
- **TerriaJS** visualises stations and discharge via GeoJSON

## Components

| Component | Purpose |
|---|---|
| `schemas/hydro_station.yaml` | ckanext-schemingdcat schema defining the `hydro_station` dataset type |
| `plugin.py` | Registers custom validators, auto-generates `spatial` GeoJSON from lat/lon |
| `validators.py` | `valid_latitude`, `valid_longitude`, `valid_uuid`, `valid_curve_params_json` |

## Installation

### 1. Install the extension

```bash
pip install -e /path/to/ckanext-stationsdischarge
```

### 2. Register the schema in `production.ini`

Add the hydro_station schema to the existing `scheming.dataset_schemas`:

```ini
scheming.dataset_schemas = ckanext.schemingdcat:schemas/unesco/dataset.yaml
                           ckanext.schemingdcat:schemas/unesco/documents.yaml
                           ckanext.stationsdischarge:schemas/hydro_station.yaml
```

### 3. Enable the plugin in `production.ini`

Add `stationsdischarge` to `ckan.plugins`:

```ini
ckan.plugins = ... schemingdcat schemingdcat_datasets ... stationsdischarge
```

### 4. Restart CKAN

```bash
# Docker
docker compose restart ckan

# Kubernetes
kubectl rollout restart deployment/ckan -n ckan
```

## MVP vs Full Extension

### MVP (schema only — no Python code needed)

If you only want the schema without custom validators, you can skip installing the plugin and just reference the YAML:

1. Copy `schemas/hydro_station.yaml` into your schemingdcat schemas directory
2. Add it to `scheming.dataset_schemas` in `production.ini`
3. No plugin needed — schemingdcat handles everything

### Full Extension (recommended)

Install the full plugin to get:
- **Custom validators**: structural validation of curve_params_json per curve_type, UUID validation for ThingsBoard IDs, lat/lon range validation
- **Auto-spatial**: automatically generates the `spatial` GeoJSON Point from latitude/longitude so ckanext-spatial indexes the station
- **Template helpers**: human-readable curve summaries (e.g. "Q = 2.5·(H − 0.15)^1.8")

## API Usage for rating-service

### Get station by station_id

```bash
curl "https://your-ckan.org/api/3/action/package_search?fq=type:hydro_station+station_id:EST-MAIPO-001"
```

### List all active stations

```bash
curl "https://your-ckan.org/api/3/action/package_search?fq=type:hydro_station+station_status:active&rows=1000"
```

### Get station by CKAN name

```bash
curl "https://your-ckan.org/api/3/action/package_show?id=est-rio-maipo-puente-manzano"
```

### Spatial search (stations within bounding box)

```bash
curl "https://your-ckan.org/api/3/action/package_search?fq=type:hydro_station&ext_bbox=-71,-34,-70,-33"
```

## Rating Curve Types

### Power law: Q = a·(H − h₀)ᵇ

```json
{"a": 2.5, "b": 1.8, "h0": 0.15}
```

### Linear segments

```json
{
  "segments": [
    {"h_min": 0.0, "h_max": 1.0, "slope": 2.5, "intercept": 0.0},
    {"h_min": 1.0, "h_max": 3.0, "slope": 5.0, "intercept": -2.5}
  ]
}
```

### Table interpolation (H–Q table)

```json
{
  "table": [
    {"h": 0.0, "q": 0.0},
    {"h": 0.5, "q": 1.2},
    {"h": 1.0, "q": 3.8},
    {"h": 2.0, "q": 12.4}
  ]
}
```

## TerriaJS Integration

The recommended approach:

1. `rating-service` exposes a GeoJSON endpoint with all stations + latest discharge
2. Register that GeoJSON URL as a **resource** in the `hydro_station` dataset in CKAN
3. TerriaJS discovers and loads the GeoJSON layer via the CKAN catalogue (already supported via `terria_view` plugin)

## License

AGPL-3.0
