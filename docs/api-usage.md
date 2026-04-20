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
  "export_format": "geojson"
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

```http
POST /api/3/action/dataset_geojson
Content-Type: application/json

{"id": "cuenca-del-maipo", "include_telemetry": true}
```

### Export dataset CSV

```http
POST /api/3/action/dataset_csv
Content-Type: application/json

{"id": "cuenca-del-maipo", "include_telemetry": true}
```

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
