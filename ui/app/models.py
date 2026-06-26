from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    sessions: Mapped[list["SessionToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[AdminUser] = relationship(back_populates="sessions")


class Backend(Base, TimestampMixin):
    __tablename__ = "backends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="http")
    scheme: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    tls_to_backend: Mapped[bool] = mapped_column(Boolean, default=False)
    send_proxy_protocol: Mapped[bool] = mapped_column(Boolean, default=False)
    keepalive: Mapped[int] = mapped_column(Integer, default=32)
    read_timeout: Mapped[int] = mapped_column(Integer, default=3600)
    send_timeout: Mapped[int] = mapped_column(Integer, default=3600)
    connect_timeout: Mapped[int] = mapped_column(Integer, default=60)
    preserve_host: Mapped[bool] = mapped_column(Boolean, default=True)
    forward_real_ip: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_options: Mapped[str] = mapped_column(Text, default="{}")

    sni_routes: Mapped[list["SniRoute"]] = relationship(back_populates="backend")
    http_routes: Mapped[list["HttpRoute"]] = relationship(back_populates="backend")


class PublicListener(Base, TimestampMixin):
    __tablename__ = "public_listeners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, default="default")
    tcp_port: Mapped[int] = mapped_column(Integer, default=443)
    udp_port: Mapped[int] = mapped_column(Integer, default=443)
    tcp_ports: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    udp_ports: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    enable_tcp_sni: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_http3: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_http80: Mapped[bool] = mapped_column(Boolean, default=True)
    listen_address_mode: Mapped[str] = mapped_column(String(16), default="split")
    default_sni_action: Mapped[str] = mapped_column(String(32), default="http_termination")
    default_backend_id: Mapped[Optional[int]] = mapped_column(ForeignKey("backends.id"), nullable=True)
    internal_http_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    internal_http_port: Mapped[int] = mapped_column(Integer, default=8443)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    default_backend: Mapped[Optional[Backend]] = relationship(foreign_keys=[default_backend_id])
    sni_routes: Mapped[list["SniRoute"]] = relationship(back_populates="listener", cascade="all, delete-orphan")


class SniRoute(Base, TimestampMixin):
    __tablename__ = "sni_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listener_id: Mapped[int] = mapped_column(ForeignKey("public_listeners.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sni: Mapped[str] = mapped_column(String(2048), index=True, nullable=False)
    alpn: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    backend_id: Mapped[Optional[int]] = mapped_column(ForeignKey("backends.id"), nullable=True)

    listener: Mapped[PublicListener] = relationship(back_populates="sni_routes")
    backend: Mapped[Optional[Backend]] = relationship(back_populates="sni_routes")


class HttpRoute(Base, TimestampMixin):
    __tablename__ = "http_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    match_type: Mapped[str] = mapped_column(String(16), default="host_path")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    backend_type: Mapped[str] = mapped_column(String(16), default="http")
    http_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    backend_id: Mapped[int] = mapped_column(ForeignKey("backends.id"), nullable=False)
    is_default_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_options: Mapped[str] = mapped_column(Text, default="{}")

    backend: Mapped[Backend] = relationship(back_populates="http_routes")


class Certificate(Base, TimestampMixin):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(2048), index=True, nullable=False)
    cert_path: Mapped[str] = mapped_column(String(512), nullable=False)
    key_path: Mapped[str] = mapped_column(String(512), nullable=False)
    managed_by_system: Mapped[bool] = mapped_column(Boolean, default=False)
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ConfigVersion(Base, TimestampMixin):
    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="generated")
    config_path: Mapped[str] = mapped_column(String(512), nullable=False)
    test_result: Mapped[str] = mapped_column(Text, default="")
    error_log: Mapped[str] = mapped_column(Text, default="")
