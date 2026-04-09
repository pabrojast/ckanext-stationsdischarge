# API Usage Guide for rating-service

This document describes how the external `rating-service` microservice should query CKAN to obtain hydrometric station configuration.

## Base URL

```
https://your-ckan-instance.org/api/3/action/
```

All endpoints return JSON with `{"success": true, "result": {...}}`.

Authentication: use an API key header if CKAN datasets are private:
```
Authorization: YOUR_CKAN_API_KEY
```

---

## 1. Get a single station by station_id

**Recommended method** — uses Solr full-text search with field filter.

```http
GET /api/3/action/package_search?fq=type:hydro_station+station_id:"EST-MAIPO-001"&rows=1
```

### Response

```json
{
  "success": true,
  "result": {
    "count": 1,
    "results": [
      {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "type": "hydro_station",
        "name": "est-rio-maipo-puente-manzano",
        "title": "Estación Río Maipo – Puente El Manzano",
        "station_id": "EST-MAIPO-001",
        "station_status": "active",
        "latitude": "-33.5982",
        "longitude": "-70.3451",
        "spatial": "{\"type\": \"Point\", \"coordinates\": [-70.3451, -33.5982]}",
        "river_name": "Río Maipo",
        "basin_name": "Cuenca del Maipo",
        "country": "Chile",
        "elevation_masl": "842",
        "thingsboard_entity_id": "784f394c-42b6-11ec-81d3-0242ac130003",
        "thingsboard_device_id": "784f394c-42b6-11ec-81d3-0242ac130003",
        "thingsboard_telemetry_key": "water_level",
        "observed_variable": "water_level",
        "unit_level": "m",
        "unit_flow": "m3/s",
        "curve_type": "power",
        "curve_params_json": "{\"a\": 2.5, \"b\": 1.8, \"h0\": 0.15}",
        "curve_valid_from": "2024-01-01",
        "curve_valid_to": "",
        "curve_notes": "Calibrada con 12 aforos. R² = 0.97",
        "owner_org": "direccion-general-aguas",
        "notes": "Estación hidrométrica en el Río Maipo.",
        "resources": []
      }
    ]
  }
}
```

### Extracting what you need (Python)

```python
import requests
import json

CKAN_URL = "https://your-ckan.org"
API_KEY = "your-api-key"  # optional for public datasets

def get_station(station_id: str) -> dict | None:
    """Fetch station config from CKAN by station_id."""
    resp = requests.get(
        f"{CKAN_URL}/api/3/action/package_search",
        params={
            "fq": f'type:hydro_station station_id:"{station_id}"',
            "rows": 1,
        },
        headers={"Authorization": API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()["result"]["results"]
    if not results:
        return None
    station = results[0]
    # Parse the curve params
    station["_curve_params"] = json.loads(station["curve_params_json"])
    return station
```

---

## 2. List all active stations

```http
GET /api/3/action/package_search?fq=type:hydro_station+station_status:active&rows=1000
```

### Python

```python
def list_active_stations() -> list[dict]:
    """Fetch all active hydro stations."""
    resp = requests.get(
        f"{CKAN_URL}/api/3/action/package_search",
        params={
            "fq": "type:hydro_station station_status:active",
            "rows": 1000,
        },
        headers={"Authorization": API_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]["results"]
```

---

## 3. Get station by CKAN dataset name/id

If you already know the CKAN package name or UUID:

```http
GET /api/3/action/package_show?id=est-rio-maipo-puente-manzano
```

---

## 4. Spatial search (stations within a bounding box)

Requires `ckanext-spatial` (already enabled).

```http
GET /api/3/action/package_search?fq=type:hydro_station&ext_bbox=-71.5,-34.0,-70.0,-33.0
```

Returns all stations whose `spatial` geometry intersects the bounding box.

---

## 5. Complete rating-service flow

```
1. rating-service calls CKAN → get_station("EST-MAIPO-001")
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

---

## 6. TerriaJS consumption

TerriaJS can load the GeoJSON endpoint from `rating-service` directly or discover it via the CKAN catalogue since `terria_view` is already enabled.

Recommended: register the rating-service GeoJSON URL as a **resource** in the CKAN `hydro_station` dataset with `format: geojson` and `resource_type: geojson`.
