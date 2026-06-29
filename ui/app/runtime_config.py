from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config_generator import NginxConfigGenerator
from .models import Backend, Certificate, HttpRoute, PublicListener, SniRoute
from .nginx_control import write_active_configs
from .seed import bootstrap, ensure_default_listener, init_db


def default_listener(db: Session) -> PublicListener:
    listener = db.execute(select(PublicListener).order_by(PublicListener.id.asc())).scalar_one_or_none()
    if listener:
        return listener
    return ensure_default_listener(db)


def generator_from_db(db: Session) -> NginxConfigGenerator:
    listener = default_listener(db)
    sni_routes = list(db.execute(select(SniRoute).order_by(SniRoute.priority.asc(), SniRoute.id.asc())).scalars())
    http_routes = list(db.execute(select(HttpRoute).order_by(HttpRoute.priority.asc(), HttpRoute.id.asc())).scalars())
    backends = list(db.execute(select(Backend).order_by(Backend.id.asc())).scalars())
    certificates = list(db.execute(select(Certificate).order_by(Certificate.id.asc())).scalars())
    return NginxConfigGenerator(listener, sni_routes, http_routes, backends, certificates)


def render_active_configs_from_db() -> None:
    init_db()
    from .database import SessionLocal

    db = SessionLocal()
    try:
        bootstrap(db)
        generated = generator_from_db(db).generate()
        write_active_configs(generated.http, generated.stream)
    finally:
        db.close()
