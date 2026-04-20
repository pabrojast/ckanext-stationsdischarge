"""SQLAlchemy model for hydro stations.

Stores hydrometric station configuration in its own table,
independent of CKAN packages/datasets.
"""

import datetime
import logging
import uuid

from sqlalchemy import Column, types

from ckan import model
from ckan.model.domain_object import DomainObject

try:
    from ckan.plugins.toolkit import BaseModel
except ImportError:
    from ckan.model.meta import metadata
    from sqlalchemy.ext.declarative import declarative_base

    BaseModel = declarative_base(metadata=metadata)

log = logging.getLogger(__name__)


def _make_uuid():
    return str(uuid.uuid4())


class HydroStation(DomainObject, BaseModel):
    """A hydrometric station with IoT connection."""

    __tablename__ = "hydro_stations"

    # ── Primary key ──
    id = Column(types.UnicodeText, primary_key=True, default=_make_uuid)

    # ── Station Identity ──
    title = Column(types.UnicodeText, nullable=False)
    name = Column(types.UnicodeText, nullable=False, unique=True)
    station_id = Column(types.UnicodeText, nullable=False, unique=True)
    owner_org = Column(types.UnicodeText)
    station_status = Column(types.UnicodeText, default="active")
    notes = Column(types.UnicodeText)
    tag_string = Column(types.UnicodeText)

    # ── Location ──
    latitude = Column(types.Float)
    longitude = Column(types.Float)
    spatial = Column(types.UnicodeText)
    river_name = Column(types.UnicodeText)
    basin_name = Column(types.UnicodeText)
    country = Column(types.UnicodeText)
    elevation_masl = Column(types.Float)

    # ── IoT Sensor Connection ──
    thingsboard_entity_id = Column(types.UnicodeText)
    thingsboard_device_id = Column(types.UnicodeText)

    # ── Submission workflow ──
    submission_status = Column(types.UnicodeText, default="draft")
    submitted_at = Column(types.DateTime)
    reviewed_at = Column(types.DateTime)
    reviewed_by = Column(types.UnicodeText)

    # ── Audit ──
    user_id = Column(types.UnicodeText)
    created = Column(types.DateTime, default=datetime.datetime.utcnow)
    modified = Column(types.DateTime, default=datetime.datetime.utcnow)

    @classmethod
    def get(cls, **kw):
        query = model.Session.query(cls)
        return query.filter_by(**kw).first()

    @classmethod
    def list_stations(
        cls,
        org_id=None,
        station_status=None,
        submission_status=None,
        q=None,
        order_by="modified",
        limit=100,
        offset=0,
    ):
        """Return filtered list of stations."""
        query = model.Session.query(cls)

        if org_id:
            query = query.filter(cls.owner_org == org_id)
        if station_status:
            query = query.filter(cls.station_status == station_status)
        if submission_status:
            query = query.filter(cls.submission_status == submission_status)
        if q:
            q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q_like = f"%{q_escaped}%"
            query = query.filter(
                cls.title.ilike(q_like, escape="\\")
                | cls.station_id.ilike(q_like, escape="\\")
                | cls.river_name.ilike(q_like, escape="\\")
                | cls.basin_name.ilike(q_like, escape="\\")
            )

        if order_by == "title":
            query = query.order_by(cls.title)
        elif order_by == "created":
            query = query.order_by(cls.created.desc())
        else:
            query = query.order_by(cls.modified.desc())

        total = query.count()
        results = query.offset(offset).limit(limit).all()
        return results, total

    def as_dict(self):
        """Serialize to dict for API responses."""
        d = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name, None)
            if isinstance(val, datetime.datetime):
                val = val.isoformat()
            d[col.name] = val
        d["telemetry_keys"] = [
            k.as_dict() for k in StationTelemetryKey.get_by_station(self.id)
        ]
        return d


class StationTelemetryKey(DomainObject, BaseModel):
    """A telemetry key associated with a station."""

    __tablename__ = "station_telemetry_keys"

    id = Column(types.UnicodeText, primary_key=True, default=_make_uuid)
    station_id = Column(types.UnicodeText, nullable=False, index=True)
    telemetry_key = Column(types.UnicodeText, nullable=False)
    label = Column(types.UnicodeText)
    unit = Column(types.UnicodeText)
    variable_type = Column(types.UnicodeText)
    sort_order = Column(types.Integer, default=0)
    created = Column(types.DateTime, default=datetime.datetime.utcnow)

    @classmethod
    def get_by_station(cls, station_id):
        """Return all keys for a station ordered by sort_order."""
        return (
            model.Session.query(cls)
            .filter(cls.station_id == station_id)
            .order_by(cls.sort_order, cls.created)
            .all()
        )

    @classmethod
    def delete_by_station(cls, station_id):
        """Delete all keys for a station."""
        model.Session.query(cls).filter(cls.station_id == station_id).delete()

    def as_dict(self):
        d = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name, None)
            if isinstance(val, datetime.datetime):
                val = val.isoformat()
            d[col.name] = val
        return d


class HydroDataset(DomainObject, BaseModel):
    """A dataset that groups multiple stations for export."""

    __tablename__ = "hydro_datasets"

    id = Column(types.UnicodeText, primary_key=True, default=_make_uuid)
    title = Column(types.UnicodeText, nullable=False)
    name = Column(types.UnicodeText, nullable=False, unique=True)
    description = Column(types.UnicodeText)
    owner_org = Column(types.UnicodeText)

    # Default query/export settings
    time_range = Column(types.UnicodeText, default="24h")
    agg = Column(types.UnicodeText)
    interval_ms = Column(types.Integer)
    export_format = Column(types.UnicodeText, default="geojson")

    user_id = Column(types.UnicodeText)
    created = Column(types.DateTime, default=datetime.datetime.utcnow)
    modified = Column(types.DateTime, default=datetime.datetime.utcnow)

    @classmethod
    def get(cls, **kw):
        query = model.Session.query(cls)
        return query.filter_by(**kw).first()

    @classmethod
    def list_datasets(cls, owner_org=None, q=None, limit=100, offset=0):
        query = model.Session.query(cls)
        if owner_org:
            query = query.filter(cls.owner_org == owner_org)
        if q:
            q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q_like = f"%{q_escaped}%"
            query = query.filter(
                cls.title.ilike(q_like, escape="\\")
                | cls.description.ilike(q_like, escape="\\")
            )
        query = query.order_by(cls.modified.desc())
        total = query.count()
        results = query.offset(offset).limit(limit).all()
        return results, total

    def as_dict(self):
        d = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name, None)
            if isinstance(val, datetime.datetime):
                val = val.isoformat()
            d[col.name] = val
        d["stations"] = [s.as_dict() for s in HydroDatasetStation.get_by_dataset(self.id)]
        return d


class HydroDatasetStation(DomainObject, BaseModel):
    """Association between a dataset and a station."""

    __tablename__ = "hydro_dataset_stations"

    id = Column(types.UnicodeText, primary_key=True, default=_make_uuid)
    dataset_id = Column(types.UnicodeText, nullable=False, index=True)
    station_id = Column(types.UnicodeText, nullable=False)
    sort_order = Column(types.Integer, default=0)

    @classmethod
    def get_by_dataset(cls, dataset_id):
        return (
            model.Session.query(cls)
            .filter(cls.dataset_id == dataset_id)
            .order_by(cls.sort_order)
            .all()
        )

    @classmethod
    def delete_by_dataset(cls, dataset_id):
        model.Session.query(cls).filter(cls.dataset_id == dataset_id).delete()

    def as_dict(self):
        d = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name, None)
            if isinstance(val, datetime.datetime):
                val = val.isoformat()
            d[col.name] = val
        return d


def init_db():
    """Create extension tables if they don't exist."""
    import sqlalchemy as sa

    try:
        engine = model.meta.engine
        inspector = sa.inspect(engine)
        existing = inspector.get_table_names()

        for tbl in (HydroStation, StationTelemetryKey, HydroDataset, HydroDatasetStation):
            if tbl.__tablename__ not in existing:
                tbl.__table__.create(engine)
                log.info("stationsdischarge: Created table '%s'", tbl.__tablename__)
            else:
                log.debug("stationsdischarge: Table '%s' already exists", tbl.__tablename__)
    except Exception as e:
        log.exception("stationsdischarge: Error initializing DB: %s", e)
        raise
