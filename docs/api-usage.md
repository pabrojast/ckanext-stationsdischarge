# API Usage Guide

This document describes how to use the CKAN API to manage hydrometric stations and datasets.

> **Note**: Stations and datasets are stored in their own database tables (not as CKAN
> packages/datasets). Use the `station_*` and `dataset_*` action API endpoints described below.

## Base URL

```
https://your-ckan-instance.org/api/3/action/
```

All endpoints return JSON with `{"success": true, "result": {...}}`.

Authentication: use an API key header for non-public stations:
```
Authorization: YOUR_CKAN_API_KEY
```

---

## 1. Get a single station

```http
POST /api/3/action/station_show
Content-Type: application/json

{"id": "EST-MAIPO-001"}
```

### Response

```json
{
  "success": true,
  "result": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "est-rio-maipo-puente-manzano",
    "title": "Estación Río Maipo – Puente El Manzano",
    "station_id": "EST-MAIPO-001",
    "station_status": "active",
    "submission_status": "approved",
    "latitude": -33.5982,
    "longitude": -70.3451,
    "spatial": "{\"type\": \"Point\", \"coordinates\": [-70.3451, -33.5982]}",
    "river_name": "Río Maipo",
    "basin_name": "Cuenca del Maipo",
    "country": "Chile",
    "elevation_masl": 842.0,
    "thingsboard_entity_id": "784f394c-42b6-11ec-81d3-0242ac130003",
    "thingsboard_device_id": "784f394c-42b6-11ec-81d3-0242ac130003",
    "telemetry_keys": [
      {"telemetry_key": "water_level", "label": "Water Level", "unit": "m", "variable_type": "water_level"},
      {"telemetry_key": "temperature", "label": "Temperature", "unit": "°C", "variable_type": "temperature"}
    ],
    "owner_org": "direccion-general-aguas",
    "notes": "Estación hidrométrica en el Río Maipo.",
    "created": "2026-04-04T10:00:00",
    "modified": "2026-04-04T18:30:00"
  }
}
```

---

## 2. List stations

```http
POST /api/3/action/station_list
Content-Type: application/json

{"station_status": "active", "limit": 1000}
```

### Filters

| Parameter          | Description                              |
|--------------------|------------------------------------------|
| `station_status`   | `active`, `inactive`, `maintenance`      |
| `submission_status`| `draft`, `pending`, `approved`, `rejected` |
| `org_id`           | Filter by organization UUID              |
| `q`                | Search in title, station_id, river, basin |
| `order_by`         | `modified` (default), `title`, `created` |
| `limit`            | Max results (default 100)                |
| `offset`           | Pagination offset                        |

---

## 3. Create a station

```http
POST /api/3/action/station_create
Content-Type: application/json
Authorization: YOUR_API_KEY

{
  "title": "Estación Río Maipo – Puente El Manzano",
  "station_id": "EST-MAIPO-001",
  "owner_org": "org-uuid-here",
  "latitude": -33.5982,
  "longitude": -70.3451,
  "thingsboard_entity_id": "784f394c-42b6-11ec-81d3-0242ac130003",
  "station_status": "active",
  "telemetry_keys": [
    {"telemetry_key": "water_level", "label": "Water Level", "unit": "m", "variable_type": "water_level"},
    {"telemetry_key": "precipitation", "label": "Precipitation", "unit": "mm", "variable_type": "precipitation"}
  ]
}
```

---

## 4. Update a station

```http
POST /api/3/action/station_update
Content-Type: application/json
Authorization: YOUR_API_KEY

{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "station_status": "maintenance",
  "telemetry_keys": [
    {"telemetry_key": "water_level", "label": "Water Level", "unit": "m", "variable_type": "water_level"}
  ]
}
```

---

## 5. Delete a station

```http
POST /api/3/action/station_delete
Content-Type: application/json
Authorization: YOUR_API_KEY

{"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
```

> Only sysadmins can delete stations.

---

## 6. Fetch ThingsBoard Metadata

Auto-fill station fields by fetching device info from ThingsBoard.

```http
POST /api/3/action/station_fetch_tb_metadata
Content-Type: application/json
Authorization: YOUR_API_KEY

{"thingsboard_entity_id": "784f394c-42b6-11ec-81d3-0242ac130003"}
```

### Response

```json
{
  "success": true,
  "result": {
    "device_name": "EST-MAIPO-001",
    "device_label": "Estación Río Maipo",
    "device_type": "HydroStation",
    "description": "...",
    "latitude": -33.5982,
    "longitude": -70.3451,
    "telemetry_keys": ["water_level", "temperature", "precipitation"],
    "server_attributes": {"...": "..."}
  }
}
```

---

## 7. Get Station Telemetry

```http
POST /api/3/action/station_telemetry
Content-Type: application/json

{
  "id": "EST-MAIPO-001",
  "keys": "water_level,temperature",
  "start_ts": 1700000000000,
  "end_ts": 1700100000000,
  "limit": 1000
}
```

Returns telemetry data grouped by key.

---

## 8. Station GeoJSON

```http
POST /api/3/action/station_geojson
Content-Type: application/json

{"id": "EST-MAIPO-001"}
```

Returns a GeoJSON Feature with station location and properties.

---

## 9. Datasets — Group stations for batch export

### Create a dataset

```http
POST /api/3/action/dataset_create
Content-Type: application/json
Authorization: YOUR_API_KEY

{
  "title": "Cuenca del Maipo",
  "owner_org": "org-uuid",
  "station_ids": ["station-uuid-1", "station-uuid-2"],
  "time_range": "24h",
  "agg": "AVG",
  "interval_ms": 3600000,
  "export_format": "geojson",

  "geojson_mode": "expanded",
  "time_property": "date",
  "display_keys": "waterLevel,temperature"
}
```

### List datasets

```http
POST /api/3/action/dataset_list
Content-Type: application/json

{"owner_org": "org-uuid", "q": "maipo"}
```

### Show a dataset

```http
POST /api/3/action/dataset_show
Content-Type: application/json

{"id": "cuenca-del-maipo"}
```

### Update a dataset

```http
POST /api/3/action/dataset_update
Content-Type: application/json
Authorization: YOUR_API_KEY

{
  "id": "dataset-uuid",
  "station_ids": ["station-uuid-1", "station-uuid-3"],
  "time_range": "7d"
}
```

### Delete a dataset

```http
POST /api/3/action/dataset_delete
Content-Type: application/json
Authorization: YOUR_API_KEY

{"id": "dataset-uuid"}
```

### Export dataset GeoJSON

Two output shapes are supported. Pick one with `mode` (or set the dataset's
stored `geojson_mode`):

- **`compact`** (default): one Feature per station with the full series in
  `properties.series[<key>]` as `[[ts_ms, value], ...]` pairs and latest
  values flattened for pop-ups. This is what the built-in dashboard reads.
- **`expanded`**: one Feature per `(station, timestamp)`. Drop the URL
  straight into TerriaJS as a GeoJSON catalog item with `timeProperty: "date"`
  and the time slider scrubs through the values. This is the simplest way
  to get an animated map of water-level / meteorological readings in Terria.

```http
POST /api/3/action/dataset_geojson
Content-Type: application/json

{
  "id": "cuenca-del-maipo",
  "mode": "expanded",
  "time_range": "30d",
  "keys": "waterLevel,temperature"
}
```

The same endpoint is exposed as `GET /hydro-dataset/<name>/geojson?mode=expanded&time_range=30d`,
which is the URL you paste into TerriaJS.

#### TerriaJS catalog item

```json
{
  "type": "geojson",
  "name": "Cuenca del Maipo",
  "url": "https://your-ckan/hydro-dataset/cuenca-del-maipo/geojson?mode=expanded&time_range=30d",
  "timeProperty": "date",
  "forceCesiumPrimitives": true,
  "featureInfoTemplate": {
    "template": "<h4>{{title}}</h4><p>{{date}}</p><p>Water level: {{waterLevel}} m</p>"
  }
}
```

The dataset detail page (`/hydro-dataset/<name>`) has an interactive builder
that emits this snippet for you with the right URL and timestamp property.

### Export dataset CSV (Terria-compatible)

```http
POST /api/3/action/dataset_csv
Content-Type: application/json

{"id": "cuenca-del-maipo", "mode": "timeseries", "time_range": "30d"}
```

Two output shapes via `mode`:

- `snapshot` (default) — one row per station; `time` is the timestamp of the
  station's latest reading. Useful for a static dot map.
- `timeseries` — one row per `(station, timestamp)`. Forces
  `include_telemetry=true` and pulls the dataset's stored time window
  (overridable via `time_range`/`start_ts`/`end_ts`/`agg`/`interval`/`limit`).

Every row leads with `lat,lon,time` so TerriaJS auto-detects the geometry and
time columns. The remaining columns are station metadata followed by one
column per telemetry key (the union of keys that returned data, alphabetical).
Rows missing lat/lon are dropped — Terria can't render them.

The same endpoint is exposed as
`GET /hydro-dataset/<name>/csv?mode=timeseries&time_range=30d` — the URL you
paste into a Terria CSV catalog item.

#### TerriaJS catalog item

```json
{
  "type": "csv",
  "name": "Cuenca del Maipo (series)",
  "url": "https://your-ckan/hydro-dataset/cuenca-del-maipo/csv?mode=timeseries&time_range=30d"
}
```

Terria reads `lat`/`lon` for geometry and `time` for the time slider with no
extra config. Telemetry-key columns appear in the style picker.

---

## 10. Web UI Endpoints

### Stations

| URL                                      | Description                |
|------------------------------------------|----------------------------|
| `/hydro-station`                         | List all stations          |
| `/hydro-station/new`                     | Create new station form    |
| `/hydro-station/<name>`                  | View station detail        |
| `/hydro-station/<name>/edit`             | Edit station form          |
| `/hydro-station/<name>/delete`           | Delete confirmation        |
| `/hydro-station/<name>/dashboard`        | Telemetry dashboard        |
| `/hydro-station/<name>/geojson`          | Station GeoJSON            |
| `/hydro-station/fetch-tb-metadata`       | Fetch ThingsBoard metadata |

### Datasets

| URL                                      | Description                |
|------------------------------------------|----------------------------|
| `/hydro-dataset`                         | List all datasets          |
| `/hydro-dataset/new`                     | Create new dataset form    |
| `/hydro-dataset/<name>`                  | View dataset detail        |
| `/hydro-dataset/<name>/edit`             | Edit dataset form          |
| `/hydro-dataset/<name>/delete`           | Delete confirmation        |
| `/hydro-dataset/<name>/geojson`          | Dataset GeoJSON export     |
| `/hydro-dataset/<name>/csv`              | Dataset CSV export         |
