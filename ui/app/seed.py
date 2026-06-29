from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .database import Base, engine
from .models import Backend, Certificate, HttpRoute, PublicListener, SniRoute


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_schema_columns()


def _ensure_schema_columns() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    statements = []
    if "public_listeners" in tables:
        columns = {column["name"] for column in inspector.get_columns("public_listeners")}
        if "tcp_ports" not in columns:
            statements.append("ALTER TABLE public_listeners ADD COLUMN tcp_ports JSON")
        if "udp_ports" not in columns:
            statements.append("ALTER TABLE public_listeners ADD COLUMN udp_ports JSON")
    if "backends" in tables:
        columns = {column["name"] for column in inspector.get_columns("backends")}
        if "send_proxy_protocol" not in columns:
            statements.append("ALTER TABLE backends ADD COLUMN send_proxy_protocol BOOLEAN DEFAULT 0 NOT NULL")
    if "http_routes" in tables:
        columns = {column["name"] for column in inspector.get_columns("http_routes")}
        if "alpn" not in columns:
            statements.append("ALTER TABLE http_routes ADD COLUMN alpn VARCHAR(128)")
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def ensure_default_listener(db: Session) -> PublicListener:
    listener = db.execute(select(PublicListener).where(PublicListener.name == "default")).scalar_one_or_none()
    if listener:
        return listener
    listener = PublicListener(
        name="default",
        tcp_port=int(os.getenv("DEFAULT_TCP_PORT", "443")),
        udp_port=int(os.getenv("DEFAULT_UDP_PORT", "443")),
        tcp_ports=[int(os.getenv("DEFAULT_TCP_PORT", "443"))],
        udp_ports=[int(os.getenv("DEFAULT_UDP_PORT", "443"))],
        enable_tcp_sni=True,
        enable_http3=os.getenv("ENABLE_HTTP3", "true").lower() == "true",
        enable_http80=True,
        listen_address_mode=os.getenv("LISTEN_ADDRESS_MODE", "split"),
        default_sni_action="http_termination",
        internal_http_host=os.getenv("INTERNAL_HTTP_HOST", "0.0.0.0"),
        internal_http_port=int(os.getenv("INTERNAL_HTTP_PORT", "8443")),
        enabled=True,
    )
    db.add(listener)
    db.commit()
    db.refresh(listener)
    return listener


def load_sample_data(db: Session, path: str | Path) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ensure_default_listener(db)
    existing = db.execute(select(Backend.id)).first()
    if existing:
        return
    backends_by_name: dict[str, Backend] = {}
    for item in data.get("backends", []):
        backend = Backend(**item)
        db.add(backend)
        db.flush()
        backends_by_name[backend.name] = backend
    for item in data.get("certificates", []):
        db.add(Certificate(**item))
    listener = db.execute(select(PublicListener).where(PublicListener.name == "default")).scalar_one()
    for item in data.get("sni_routes", []):
        backend_name = item.pop("backend_name", None)
        item["listener_id"] = listener.id
        if backend_name:
            item["backend_id"] = backends_by_name[backend_name].id
        db.add(SniRoute(**item))
    for item in data.get("http_routes", []):
        backend_name = item.pop("backend_name")
        item["backend_id"] = backends_by_name[backend_name].id
        db.add(HttpRoute(**item))
    db.commit()


def bootstrap(db: Session) -> None:
    ensure_default_listener(db)
    sample = os.getenv("SAMPLE_DATA_JSON")
    if sample and Path(sample).exists():
        load_sample_data(db, sample)
