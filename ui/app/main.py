from __future__ import annotations

import os
from pathlib import Path
from typing import Type, TypeVar

from fastapi import Body
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config_generator import NginxConfigGenerator
from .database import get_db
from .models import AdminUser, Backend, Certificate, ConfigVersion, HttpRoute, PublicListener, SessionToken, SniRoute
from .nginx_control import apply_configs, rollback_to, tail_log
from .schemas import (
    AdminInit,
    AuthState,
    BackendIn,
    BackendOut,
    CertificateBulkReplaceIn,
    CertificateIn,
    CertificateOut,
    ConfigApplyResult,
    ConfigPreview,
    ConfigVersionOut,
    HttpRouteIn,
    HttpRouteOut,
    ListenerIn,
    ListenerOut,
    LoginRequest,
    SniRouteIn,
    SniRouteOut,
)
from .security import (
    SESSION_COOKIE,
    admin_count,
    clear_session_cookie,
    current_user_optional,
    hash_password,
    issue_session,
    remove_current_session,
    require_user,
    verify_password,
)
from .seed import bootstrap, init_db

T = TypeVar("T")


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


PRODUCT_NAME = "OmniProxyGate"
WEB_UI_ENABLED = _truthy_env("OMNI_WEB_UI_ENABLED", "true")

app = FastAPI(title=PRODUCT_NAME, version="1.0.0-mvp")
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
if WEB_UI_ENABLED:
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _bootstrap_admin_from_env(db: Session) -> None:
    password = os.getenv("OMNI_ADMIN_PASSWORD")
    if not password:
        return

    username = os.getenv("OMNI_ADMIN_USER", "admin")
    force_reset = _truthy_env("OMNI_ADMIN_FORCE_PASSWORD_RESET")
    user = db.execute(select(AdminUser).where(AdminUser.username == username)).scalar_one_or_none()

    if user is None:
        if admin_count(db) > 0 and not force_reset:
            return
        user = AdminUser(username=username, password_hash=hash_password(password))
        db.add(user)
    elif force_reset:
        user.password_hash = hash_password(password)
        db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    else:
        return
    db.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    # Use a short-lived session to create the default listener and optional sample data.
    from .database import SessionLocal

    db = SessionLocal()
    try:
        bootstrap(db)
        _bootstrap_admin_from_env(db)
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not WEB_UI_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="web UI disabled")
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/state", response_model=AuthState)
def auth_state(
    db: Session = Depends(get_db),
    user: AdminUser | None = Depends(current_user_optional),
) -> AuthState:
    return AuthState(initialized=admin_count(db) > 0, authenticated=user is not None, username=user.username if user else None)


@app.post("/api/auth/init", response_model=AuthState)
def init_admin(payload: AdminInit, response: Response, db: Session = Depends(get_db)) -> AuthState:
    if admin_count(db) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="admin user already initialized")
    user = AdminUser(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    issue_session(db, user, response)
    return AuthState(initialized=True, authenticated=True, username=user.username)


@app.post("/api/auth/login", response_model=AuthState)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthState:
    user = db.execute(select(AdminUser).where(AdminUser.username == payload.username)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    issue_session(db, user, response)
    return AuthState(initialized=True, authenticated=True, username=user.username)


@app.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    cookie_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    remove_current_session(db, response, request, cookie_token)
    clear_session_cookie(response)
    return {"ok": True}


def _get_or_404(db: Session, model: Type[T], item_id: int) -> T:
    obj = db.get(model, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return obj


def _commit_or_400(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate or invalid record") from exc


def _default_listener(db: Session) -> PublicListener:
    listener = db.execute(select(PublicListener).order_by(PublicListener.id.asc())).scalar_one_or_none()
    if not listener:
        listener = PublicListener(name="default")
        db.add(listener)
        _commit_or_400(db)
        db.refresh(listener)
    return listener


@app.get("/api/listener", response_model=ListenerOut, dependencies=[Depends(require_user)])
def get_listener(db: Session = Depends(get_db)) -> PublicListener:
    return _default_listener(db)


@app.put("/api/listener", response_model=ListenerOut, dependencies=[Depends(require_user)])
def update_listener(payload: ListenerIn, db: Session = Depends(get_db)) -> PublicListener:
    listener = _default_listener(db)
    for key, value in payload.model_dump().items():
        setattr(listener, key, value)
    _commit_or_400(db)
    db.refresh(listener)
    return listener


@app.get("/api/backends", response_model=list[BackendOut], dependencies=[Depends(require_user)])
def list_backends(db: Session = Depends(get_db)) -> list[Backend]:
    return list(db.execute(select(Backend).order_by(Backend.id.asc())).scalars())


@app.post("/api/backends", response_model=BackendOut, dependencies=[Depends(require_user)])
def create_backend(payload: BackendIn, db: Session = Depends(get_db)) -> Backend:
    obj = Backend(**payload.model_dump())
    db.add(obj)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.put("/api/backends/{item_id}", response_model=BackendOut, dependencies=[Depends(require_user)])
def update_backend(item_id: int, payload: BackendIn, db: Session = Depends(get_db)) -> Backend:
    obj = _get_or_404(db, Backend, item_id)
    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.delete("/api/backends/{item_id}", dependencies=[Depends(require_user)])
def delete_backend(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    obj = _get_or_404(db, Backend, item_id)
    db.delete(obj)
    _commit_or_400(db)
    return {"ok": True}


@app.get("/api/certificates", response_model=list[CertificateOut], dependencies=[Depends(require_user)])
def list_certificates(db: Session = Depends(get_db)) -> list[Certificate]:
    return list(db.execute(select(Certificate).order_by(Certificate.id.asc())).scalars())


@app.post("/api/certificates", response_model=CertificateOut, dependencies=[Depends(require_user)])
def create_certificate(payload: CertificateIn, db: Session = Depends(get_db)) -> Certificate:
    obj = Certificate(**payload.model_dump())
    db.add(obj)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.put("/api/certificates/{item_id}", response_model=CertificateOut, dependencies=[Depends(require_user)])
def update_certificate(item_id: int, payload: CertificateIn, db: Session = Depends(get_db)) -> Certificate:
    obj = _get_or_404(db, Certificate, item_id)
    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.post("/api/certificates/bulk-replace", response_model=list[CertificateOut], dependencies=[Depends(require_user)])
def bulk_replace_certificates(payload: CertificateBulkReplaceIn, db: Session = Depends(get_db)) -> list[Certificate]:
    replace_ids = [item_id for item_id in dict.fromkeys(payload.replace_ids) if item_id]
    try:
        existing = []
        if replace_ids:
            existing = list(db.execute(select(Certificate).where(Certificate.id.in_(replace_ids))).scalars())
            found_ids = {item.id for item in existing}
            missing = [item_id for item_id in replace_ids if item_id not in found_ids]
            if missing:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"certificate ids not found: {missing}")

        for obj in existing:
            db.delete(obj)
        db.flush()

        created: list[Certificate] = []
        for item in payload.certificates:
            obj = Certificate(**item.model_dump())
            db.add(obj)
            created.append(obj)
        db.flush()

        db.commit()
        for obj in created:
            db.refresh(obj)
        return created
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate or invalid certificate record") from exc


@app.delete("/api/certificates/{item_id}", dependencies=[Depends(require_user)])
def delete_certificate(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    obj = _get_or_404(db, Certificate, item_id)
    db.delete(obj)
    _commit_or_400(db)
    return {"ok": True}


@app.get("/api/sni-routes", response_model=list[SniRouteOut], dependencies=[Depends(require_user)])
def list_sni_routes(db: Session = Depends(get_db)) -> list[SniRoute]:
    return list(db.execute(select(SniRoute).order_by(SniRoute.priority.asc(), SniRoute.id.asc())).scalars())


@app.post("/api/sni-routes", response_model=SniRouteOut, dependencies=[Depends(require_user)])
def create_sni_route(payload: SniRouteIn, db: Session = Depends(get_db)) -> SniRoute:
    obj = SniRoute(**payload.model_dump())
    db.add(obj)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.put("/api/sni-routes/{item_id}", response_model=SniRouteOut, dependencies=[Depends(require_user)])
def update_sni_route(item_id: int, payload: SniRouteIn, db: Session = Depends(get_db)) -> SniRoute:
    obj = _get_or_404(db, SniRoute, item_id)
    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.delete("/api/sni-routes/{item_id}", dependencies=[Depends(require_user)])
def delete_sni_route(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    obj = _get_or_404(db, SniRoute, item_id)
    db.delete(obj)
    _commit_or_400(db)
    return {"ok": True}


@app.get("/api/http-routes", response_model=list[HttpRouteOut], dependencies=[Depends(require_user)])
def list_http_routes(db: Session = Depends(get_db)) -> list[HttpRoute]:
    return list(db.execute(select(HttpRoute).order_by(HttpRoute.priority.asc(), HttpRoute.id.asc())).scalars())


@app.post("/api/http-routes", response_model=HttpRouteOut, dependencies=[Depends(require_user)])
def create_http_route(payload: HttpRouteIn, db: Session = Depends(get_db)) -> HttpRoute:
    obj = HttpRoute(**payload.model_dump())
    db.add(obj)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.put("/api/http-routes/{item_id}", response_model=HttpRouteOut, dependencies=[Depends(require_user)])
def update_http_route(item_id: int, payload: HttpRouteIn, db: Session = Depends(get_db)) -> HttpRoute:
    obj = _get_or_404(db, HttpRoute, item_id)
    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    _commit_or_400(db)
    db.refresh(obj)
    return obj


@app.delete("/api/http-routes/{item_id}", dependencies=[Depends(require_user)])
def delete_http_route(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    obj = _get_or_404(db, HttpRoute, item_id)
    db.delete(obj)
    _commit_or_400(db)
    return {"ok": True}


def _dump_item(obj: object, fields: list[str]) -> dict:
    return {field: getattr(obj, field) for field in fields}


def _export_bundle(db: Session) -> dict:
    listener = _default_listener(db)
    return {
        "kind": "omni-proxygate-config",
        "version": 1,
        "product": PRODUCT_NAME,
        "listener": _dump_item(listener, [
            "id", "name", "tcp_port", "udp_port", "tcp_ports", "udp_ports", "enable_tcp_sni", "enable_http3",
            "enable_http80", "listen_address_mode", "default_sni_action", "default_backend_id",
            "internal_http_host", "internal_http_port", "enabled",
        ]),
        "backends": [
            _dump_item(item, [
                "id", "name", "host", "port", "protocol", "scheme", "tls_to_backend", "send_proxy_protocol",
                "keepalive", "read_timeout", "send_timeout", "connect_timeout", "preserve_host",
                "forward_real_ip", "extra_options",
            ])
            for item in db.execute(select(Backend).order_by(Backend.id.asc())).scalars()
        ],
        "certificates": [
            _dump_item(item, ["id", "name", "domain", "cert_path", "key_path", "managed_by_system", "expire_at"])
            for item in db.execute(select(Certificate).order_by(Certificate.id.asc())).scalars()
        ],
        "sni_routes": [
            _dump_item(item, ["id", "listener_id", "name", "enabled", "sni", "alpn", "priority", "action", "backend_id"])
            for item in db.execute(select(SniRoute).order_by(SniRoute.priority.asc(), SniRoute.id.asc())).scalars()
        ],
        "http_routes": [
            _dump_item(item, [
                "id", "name", "enabled", "host", "path", "match_type", "priority", "backend_type", "http_mode",
                "backend_id", "is_default_fallback", "extra_options",
            ])
            for item in db.execute(select(HttpRoute).order_by(HttpRoute.priority.asc(), HttpRoute.id.asc())).scalars()
        ],
    }


@app.get("/api/config/export", dependencies=[Depends(require_user)])
def export_config(db: Session = Depends(get_db)) -> dict:
    return _export_bundle(db)


@app.post("/api/config/import", dependencies=[Depends(require_user)])
def import_config(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict[str, bool | int]:
    if payload.get("kind") != "omni-proxygate-config":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported config bundle")

    listener_payload = ListenerIn(**payload.get("listener", {})).model_dump()
    backends_payload = [BackendIn(**item).model_dump() | {"id": item.get("id")} for item in payload.get("backends", [])]
    certs_payload = [CertificateIn(**item).model_dump() | {"id": item.get("id")} for item in payload.get("certificates", [])]
    listener_id = payload.get("listener", {}).get("id")
    sni_payload = [SniRouteIn(**item).model_dump() | {"id": item.get("id")} for item in payload.get("sni_routes", [])]
    http_payload = [HttpRouteIn(**item).model_dump() | {"id": item.get("id")} for item in payload.get("http_routes", [])]

    db.execute(delete(SniRoute))
    db.execute(delete(HttpRoute))
    db.execute(delete(Certificate))
    db.execute(delete(PublicListener))
    db.execute(delete(Backend))
    db.flush()

    for item in backends_payload:
        item = {k: v for k, v in item.items() if v is not None or k != "id"}
        db.add(Backend(**item))
    db.flush()

    listener_data = listener_payload | ({"id": listener_id} if listener_id is not None else {})
    db.add(PublicListener(**listener_data))
    db.flush()

    for item in certs_payload:
        item = {k: v for k, v in item.items() if v is not None or k != "id"}
        db.add(Certificate(**item))
    for item in sni_payload:
        item = {k: v for k, v in item.items() if v is not None or k != "id"}
        db.add(SniRoute(**item))
    for item in http_payload:
        item = {k: v for k, v in item.items() if v is not None or k != "id"}
        db.add(HttpRoute(**item))

    _commit_or_400(db)
    return {
        "ok": True,
        "backends": len(backends_payload),
        "certificates": len(certs_payload),
        "sni_routes": len(sni_payload),
        "http_routes": len(http_payload),
    }


def _generator_from_db(db: Session) -> NginxConfigGenerator:
    listener = _default_listener(db)
    sni_routes = list(db.execute(select(SniRoute).order_by(SniRoute.priority.asc(), SniRoute.id.asc())).scalars())
    http_routes = list(db.execute(select(HttpRoute).order_by(HttpRoute.priority.asc(), HttpRoute.id.asc())).scalars())
    backends = list(db.execute(select(Backend).order_by(Backend.id.asc())).scalars())
    certificates = list(db.execute(select(Certificate).order_by(Certificate.id.asc())).scalars())
    return NginxConfigGenerator(listener, sni_routes, http_routes, backends, certificates)


@app.get("/api/config/preview", response_model=ConfigPreview, dependencies=[Depends(require_user)])
def preview_config(db: Session = Depends(get_db)) -> ConfigPreview:
    generated = _generator_from_db(db).generate()
    return ConfigPreview(http=generated.http, stream=generated.stream)


@app.post("/api/config/apply", response_model=ConfigApplyResult, dependencies=[Depends(require_user)])
def apply_config(db: Session = Depends(get_db)) -> ConfigApplyResult:
    generated = _generator_from_db(db).generate()
    outcome = apply_configs(generated.http, generated.stream)
    cv = ConfigVersion(
        version=outcome.version or "unknown",
        status="active" if outcome.ok else "failed",
        config_path=str(outcome.path or ""),
        test_result=outcome.test_result,
        error_log=outcome.error_log,
    )
    db.add(cv)
    _commit_or_400(db)
    return ConfigApplyResult(ok=outcome.ok, version=outcome.version, test_result=outcome.test_result, error_log=outcome.error_log)


@app.get("/api/config/versions", response_model=list[ConfigVersionOut], dependencies=[Depends(require_user)])
def list_versions(db: Session = Depends(get_db)) -> list[ConfigVersion]:
    return list(db.execute(select(ConfigVersion).order_by(ConfigVersion.id.desc()).limit(50)).scalars())


@app.post("/api/config/rollback/{version_id}", response_model=ConfigApplyResult, dependencies=[Depends(require_user)])
def rollback_config(version_id: int, db: Session = Depends(get_db)) -> ConfigApplyResult:
    version = _get_or_404(db, ConfigVersion, version_id)
    outcome = rollback_to(version.config_path)
    version.status = "rolled_back_active" if outcome.ok else "rollback_failed"
    version.test_result = outcome.test_result
    version.error_log = outcome.error_log
    _commit_or_400(db)
    return ConfigApplyResult(ok=outcome.ok, version=outcome.version, test_result=outcome.test_result, error_log=outcome.error_log)


@app.get("/api/logs/{log_name}", response_class=PlainTextResponse, dependencies=[Depends(require_user)])
def logs(log_name: str, lines: int = 300) -> str:
    return tail_log(log_name, lines)
