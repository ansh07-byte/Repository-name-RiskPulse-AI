from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from config import ALLOW_SQLITE_FALLBACK, DATABASE_URL, ROOT, SQLITE_FALLBACK_URL


class Base(DeclarativeBase): pass


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[float] = mapped_column(Float)
    product_code: Mapped[str] = mapped_column(String(32))
    device_type: Mapped[str] = mapped_column(String(64))
    fraud_probability: Mapped[float] = mapped_column(Float)
    actual_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reasons: Mapped[str] = mapped_column(String(512))
    inference_ms: Mapped[float] = mapped_column(Float)
    blockchain_status: Mapped[str] = mapped_column(String(64))
    blockchain_tx_hash: Mapped[str] = mapped_column(String(128), default="")
    is_high_risk: Mapped[bool] = mapped_column(Boolean, index=True)
    velocity_tpm: Mapped[float] = mapped_column(Float, default=0.0)
    velocity_alert: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    freshness_ms: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_alert: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


def connect_engine():
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection: connection.execute(select(1))
        backend = "PostgreSQL"
    except Exception:
        if not ALLOW_SQLITE_FALLBACK: raise
        engine = create_engine(SQLITE_FALLBACK_URL)
        backend = "SQLite fallback (PostgreSQL unavailable)"
    return engine, backend


ENGINE, BACKEND = connect_engine()


def ensure_event_schema():
    """Create or safely migrate the events table before new monitoring fields are used."""
    inspector = inspect(ENGINE)
    if "events" not in inspector.get_table_names():
        Base.metadata.create_all(ENGINE)
        return

    existing = {column["name"] for column in inspector.get_columns("events")}
    required = {
        "velocity_tpm": "FLOAT NOT NULL DEFAULT 0",
        "velocity_alert": "BOOLEAN NOT NULL DEFAULT FALSE",
        "source_timestamp": "TIMESTAMP NULL",
        "freshness_ms": "FLOAT NOT NULL DEFAULT 0",
        "freshness_alert": "BOOLEAN NOT NULL DEFAULT FALSE",
    }
    missing = {name: ddl for name, ddl in required.items() if name not in existing}
    if not missing:
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_table = f"events_backup_{stamp}"
    if ENGINE.dialect.name == "sqlite":
        sqlite_path = Path(ENGINE.url.database) if ENGINE.url.database else ROOT / "data" / "riskpulse_fallback.db"
        if sqlite_path.exists():
            shutil.copy2(sqlite_path, sqlite_path.with_name(f"riskpulse_fallback_before_monitoring_{stamp}.db"))

    with ENGINE.begin() as connection:
        if ENGINE.dialect.name == "postgresql":
            connection.execute(text(f"CREATE TABLE {backup_table} AS TABLE events"))
        else:
            connection.execute(text(f"CREATE TABLE {backup_table} AS SELECT * FROM events"))
        for name, ddl in missing.items():
            connection.execute(text(f"ALTER TABLE events ADD COLUMN {name} {ddl}"))


ensure_event_schema()


def save_event(payload):
    with Session(ENGINE) as session:
        session.add(Event(**payload)); session.commit()
    export_powerbi_csv()


def save_events(payloads):
    """Persist a controlled traffic burst in one transaction and export once."""
    with Session(ENGINE) as session:
        session.add_all(Event(**payload) for payload in payloads)
        session.commit()
    export_powerbi_csv()


def count_events():
    with Session(ENGINE) as session:
        return session.scalar(select(func.count()).select_from(Event)) or 0


def recent_events(limit=200):
    with Session(ENGINE) as session:
        return list(session.scalars(select(Event).order_by(Event.timestamp.desc()).limit(limit)))


def export_powerbi_csv():
    path = ROOT / "powerbi" / "riskpulse_transactions.csv"
    path.parent.mkdir(exist_ok=True)
    fields = [c.name for c in Event.__table__.columns]
    rows = recent_events(50000)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(fields)
        for row in rows: writer.writerow([getattr(row, field) for field in fields])
    return path
