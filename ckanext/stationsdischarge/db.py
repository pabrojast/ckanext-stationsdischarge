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
    """A hydrometric station with IoT connection and rating curve."""

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
    thingsboard_telemetry_key = Column(types.UnicodeText)
    observed_variable = Column(types.UnicodeText)

    # ── Measurement Units ──
    unit_level = Column(types.UnicodeText, default="m")
    unit_flow = Column(types.UnicodeText, default="m3/s")

    # ── Rating Curve ──
    curve_type = Column(types.UnicodeText, default="power")
    curve_params_json = Column(types.UnicodeText)
    curve_valid_from = Column(types.UnicodeText)
    curve_valid_to = Column(types.UnicodeText)
    curve_notes = Column(types.UnicodeText)

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
    def list_stations(cls, org_id=None, station_status=None,
                      submission_status=None, q=None,
                      order_by="modified", limit=100, offset=0):
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
        return d


# Backward-compatible alias used by older deployments/imports.
HydroDatasetStation = HydroStation


def init_db():
    """Create the hydro_stations table if it doesn't exist."""
    import sqlalchemy as sa
    try:
        engine = model.meta.engine
        inspector = sa.inspect(engine)
        if "hydro_stations" not in inspector.get_table_names():
            HydroStation.__table__.create(engine)
            log.info("stationsdischarge: Created table 'hydro_stations'")
        else:
            log.debug("stationsdischarge: Table 'hydro_stations' already exists")
    except Exception as e:
        log.exception("stationsdischarge: Error initializing DB: %s", e)
        raise
