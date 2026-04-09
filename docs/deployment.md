# Deployment Guide

## production.ini Changes

### 1. Add the schema to `scheming.dataset_schemas`

Find the line:
```ini
scheming.dataset_schemas = ckanext.schemingdcat:schemas/unesco/dataset.yaml
                           ckanext.schemingdcat:schemas/unesco/documents.yaml
```

Change it to:
```ini
scheming.dataset_schemas = ckanext.schemingdcat:schemas/unesco/dataset.yaml
                           ckanext.schemingdcat:schemas/unesco/documents.yaml
                           ckanext.stationsdischarge:schemas/hydro_station.yaml
```

### 2. Add the plugin to `ckan.plugins`

Add `stationsdischarge` to the plugins list:
```ini
ckan.plugins = ... schemingdcat schemingdcat_datasets ... stationsdischarge
```

> **Note**: `stationsdischarge` must appear AFTER `schemingdcat` and `schemingdcat_datasets`.

---

## Docker Deployment

### Add to Dockerfile

In `/home/pabrojast/Proyectos/ckan-unesco-docker/Dockerfile`, add:

```dockerfile
# ckanext-stationsdischarge
RUN pip install -e git+https://github.com/pabrojast/ckanext-stationsdischarge.git#egg=ckanext-stationsdischarge
```

Or if installing from local source:
```dockerfile
COPY ./ckanext-stationsdischarge /srv/app/src/ckanext-stationsdischarge
RUN pip install -e /srv/app/src/ckanext-stationsdischarge
```

### Build and deploy

```bash
cd /home/pabrojast/Proyectos/ckan-unesco-docker
docker compose build ckan
docker compose up -d ckan
```

---

## Kubernetes Deployment

The existing CI/CD pipeline (`.github/workflows/push.yml`) will pick up the Dockerfile changes. Just:

1. Add the `pip install` line to the Dockerfile
2. Update `production.ini` with the schema and plugin
3. Push to the repository
4. The pipeline will build and deploy to DigitalOcean Kubernetes

### Manual rollout (if needed)

```bash
kubectl rollout restart deployment/ckan -n ckan
```

---

## MVP Deployment (Schema Only, No Plugin)

If you want to deploy just the schema without the Python plugin:

1. Copy `hydro_station.yaml` into the schemingdcat schemas directory:
   ```bash
   # Inside the CKAN container or Docker build
   cp hydro_station.yaml /srv/app/src/ckanext-schemingdcat/ckanext/schemingdcat/schemas/hydro_station.yaml
   ```

2. Reference it in `production.ini`:
   ```ini
   scheming.dataset_schemas = ckanext.schemingdcat:schemas/unesco/dataset.yaml
                              ckanext.schemingdcat:schemas/unesco/documents.yaml
                              ckanext.schemingdcat:schemas/hydro_station.yaml
   ```

3. No plugin to enable — schemingdcat handles everything.

> This approach gives you the full form and API without custom validators. Add the plugin later for V2 features.

---

## Solr Configuration

The `station_id` field should be searchable via `fq` (filter query). By default, CKAN stores extra fields in Solr's `extras_*` dynamic fields which are indexed.

If you need `station_id` as a dedicated Solr field for performance, add to your `schema.xml`:

```xml
<field name="station_id" type="string" indexed="true" stored="true" />
```

And update the `before_dataset_index` method in the plugin to copy it. For most deployments the default extras indexing is sufficient.

---

## Verification

After deployment, verify the schema is loaded:

```bash
# Create a test station
curl -X POST https://your-ckan.org/api/3/action/package_create \
  -H "Authorization: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "hydro_station",
    "title": "Test Station",
    "name": "test-station-001",
    "station_id": "TEST-001",
    "owner_org": "your-org-id",
    "station_status": "active",
    "latitude": "-33.45",
    "longitude": "-70.65",
    "thingsboard_entity_id": "00000000-0000-0000-0000-000000000001",
    "thingsboard_telemetry_key": "water_level",
    "observed_variable": "water_level",
    "unit_level": "m",
    "unit_flow": "m3/s",
    "curve_type": "power",
    "curve_params_json": "{\"a\": 1.0, \"b\": 1.5, \"h0\": 0.0}"
  }'

# Verify it's searchable
curl "https://your-ckan.org/api/3/action/package_search?fq=type:hydro_station"

# Clean up
curl -X POST https://your-ckan.org/api/3/action/package_delete \
  -H "Authorization: YOUR_API_KEY" \
  -d '{"id": "test-station-001"}'
```
