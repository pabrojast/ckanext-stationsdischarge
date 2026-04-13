# API Usage Guide for rating-service

This document describes how the external `rating-service` microservice should query CKAN to obtain hydrometric station configuration.

> **Note**: Stations are stored in their own database table (not as CKAN
> packages/datasets). Use the `station_*` action API endpoints described below.

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

## 1. Get a single station by station_id or name

```http
POST /api/3/action/station_show
Content-Type: application/json

{"id": "EST-MAIPO-001"}
```

Or by URL slug:

```http
POST /api/3/action/station_show
Content-Type: application/json

{"id": "est-rio-maipo-puente-manzano"}
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
    "thingsboard_telemetry_key": "water_level",
    "observed_variable": "water_level",
    "unit_level": "m",
    "unit_flow": "m3/s",
    "curve_type": "power",
    "curve_params_json": "{\"a\": 2.5, \"b\": 1.8, \"h0\": 0.15}",
    "curve_valid_from": "2024-01-01",
    "curve_valid_to": null,
    "curve_notes": "Calibrada con 12 aforos. R² = 0.97",
    "owner_org": "direccion-general-aguas",
    "notes": "Estación hidrométrica en el Río Maipo.",
    "user_id": "...",
    "created": "2026-04-04T10:00:00",
    "modified": "2026-04-04T18:30:00"
  }
}
```

### Python client

```python
import requests
import json

CKAN_URL = "https://your-ckan.org"
API_KEY = "your-api-key"  # optional for approved/public stations

def get_station(station_id: str) -> dict | None:
    """Fetch station config from CKAN by station_id."""
    resp = requests.post(
        f"{CKAN_URL}/api/3/action/station_show",
        json={"id": station_id},
        headers={"Authorization": API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data["success"]:
        return None
    station = data["result"]
    station["_curve_params"] = json.loads(station["curve_params_json"])
    return station
```

---

## 2. List all active stations

```http
POST /api/3/action/station_list
Content-Type: application/json

{"station_status": "active", "limit": 1000}
```

### Optional filters

| Parameter          | Description                              |
|--------------------|------------------------------------------|
| `station_status`   | `active`, `inactive`, `maintenance`      |
| `submission_status`| `draft`, `pending`, `approved`, `rejected` |
| `org_id`           | Filter by organization UUID              |
| `q`                | Search in title, station_id, river, basin |
| `order_by`         | `modified` (default), `title`, `created` |
| `limit`            | Max results (default 100)                |
| `offset`           | Pagination offset                        |

### Response

```json
{
  "success": true,
  "result": {
    "results": [ ... ],
    "count": 42
  }
}
```

### Python

```python
def list_active_stations() -> list[dict]:
    """Fetch all active, approved hydro stations."""
    resp = requests.post(
        f"{CKAN_URL}/api/3/action/station_list",
        json={"station_status": "active", "limit": 1000},
        headers={"Authorization": API_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]["results"]
```

---

## 3. Create a station (programmatically)

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
  "thingsboard_telemetry_key": "water_level",
  "observed_variable": "water_level",
  "station_status": "active",
  "unit_level": "m",
  "unit_flow": "m3/s",
  "curve_type": "power",
  "curve_params_json": "{\"a\": 2.5, \"b\": 1.8, \"h0\": 0.15}"
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
  "curve_params_json": "{\"a\": 2.8, \"b\": 1.75, \"h0\": 0.12}",
  "curve_notes": "Re-calibrated with 18 gaugings. R² = 0.98"
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

## 5b. Curve types reference

| `curve_type` | `curve_params_json` format | Description |
|---|---|---|
| `power` | `{"a": 2.5, "b": 1.8, "h0": 0.15}` | Q = a·(H − h₀)ᵇ |
| `linear_segments` | `{"segments": [{"h_min":0, "h_max":1.5, "slope":15, "intercept":0}, ...]}` | Piecewise linear |
| `table_interpolation` | `{"table": [{"h":0, "q":0}, {"h":0.5, "q":1.2}, ...]}` | H–Q lookup table (≥2 rows) |
| `piecewise_power` | `{"segments": [{"h_max":1.8, "a":38.91, "b":1.93}, {"a":30.53, "b":2.34}]}` | Multiple Q = a·Hᵇ segments |

### Piecewise power details

Each segment has `a` (coefficient), `b` (exponent), and optional `h_max` (upper bound).
The last segment acts as the catch-all for values above all `h_max` thresholds.

**Optional raw-value transform**: add `"transform_offset"` and `"transform_divisor"` at the
top level to convert raw sensor values before applying the power law:

```
H = transform_offset − raw_value / transform_divisor
```

Example: sensor reads 570 (cm), offset 7.5, divisor 100 → H = 7.5 − 570/100 = 1.80 m

```json
{
  "transform_offset": 7.5,
  "transform_divisor": 100,
  "segments": [
    {"h_max": 1.8, "a": 38.9106, "b": 1.9312},
    {"a": 30.5312, "b": 2.3428}
  ]
}
```

If `H ≤ 0` after the transform, discharge is 0.

---

## 6. Web UI Endpoints

| URL                            | Description              |
|--------------------------------|--------------------------|
| `/hydro-station`               | List all stations        |
| `/hydro-station/new`           | Create new station form  |
| `/hydro-station/<name>`        | View station detail      |
| `/hydro-station/<name>/edit`   | Edit station form        |
| `/hydro-station/<name>/delete` | Delete confirmation      |

---

## 7. Complete rating-service flow

```
1. rating-service calls CKAN → station_show(id="EST-MAIPO-001")
2. Extracts: thingsboard_entity_id, thingsboard_telemetry_key
3. Calls ThingsBoard API:
   GET /api/plugins/telemetry/DEVICE/{entity_id}/values/timeseries?keys=water_level
4. Gets water_level = 1.85 m
5. Reads curve_type = "power", curve_params = {"a": 2.5, "b": 1.8, "h0": 0.15}
6. Computes: Q = 2.5 * (1.85 - 0.15)^1.8 = 6.89 m³/s
7. Returns GeoJSON with station location + computed discharge
```

### Example GeoJSON output from rating-service

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-70.3451, -33.5982]
      },
      "properties": {
        "station_id": "EST-MAIPO-001",
        "station_name": "Estación Río Maipo – Puente El Manzano",
        "water_level_m": 1.85,
        "discharge_m3s": 6.89,
        "timestamp": "2026-04-04T18:30:00Z",
        "unit_level": "m",
        "unit_flow": "m3/s",
        "station_status": "active"
      }
    }
  ]
}
```
