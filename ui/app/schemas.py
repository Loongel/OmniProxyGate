from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .validators import (
    BACKEND_PROTOCOLS,
    BACKEND_TYPES,
    HTTP_MODES,
    LISTEN_ADDRESS_MODES,
    MATCH_TYPES,
    SNI_ACTIONS,
    require_choice,
    validate_backend_host,
    validate_backend_name,
    validate_domain,
    validate_domain_list,
    validate_file_path,
    validate_path,
    validate_port,
    validate_timeout,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AdminInit(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthState(BaseModel):
    initialized: bool
    authenticated: bool
    username: Optional[str] = None


PortValue = Union[int, list[int], str]


def parse_ports(value: PortValue, field_name: str) -> list[int]:
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, str):
        raw_values = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    else:
        raw_values = [value]
    ports: list[int] = []
    for raw in raw_values:
        port = validate_port(int(raw))
        if port not in ports:
            ports.append(port)
    if not ports:
        raise ValueError(f"{field_name} must contain at least one port")
    return ports


class ListenerIn(BaseModel):
    name: str = "default"
    tcp_port: PortValue = 443
    udp_port: PortValue = 443
    tcp_ports: Optional[list[int]] = None
    udp_ports: Optional[list[int]] = None
    enable_tcp_sni: bool = True
    enable_http3: bool = True
    enable_http80: bool = True
    listen_address_mode: str = "split"
    default_sni_action: str = "http_termination"
    default_backend_id: Optional[int] = None
    internal_http_host: str = "127.0.0.1"
    internal_http_port: int = 8443
    enabled: bool = True

    @field_validator("internal_http_port")
    @classmethod
    def ports(cls, value: int) -> int:
        return validate_port(value)

    @field_validator("listen_address_mode")
    @classmethod
    def listen_mode(cls, value: str) -> str:
        return require_choice(value, LISTEN_ADDRESS_MODES, "listen_address_mode")

    @field_validator("default_sni_action")
    @classmethod
    def sni_action(cls, value: str) -> str:
        return require_choice(value, SNI_ACTIONS, "default_sni_action")

    @field_validator("internal_http_host")
    @classmethod
    def internal_host(cls, value: str) -> str:
        return validate_backend_host(value, "internal_http_host")

    @model_validator(mode="after")
    def default_backend_needed(self) -> "ListenerIn":
        tcp_ports = parse_ports(self.tcp_ports if self.tcp_ports else self.tcp_port, "tcp_port")
        udp_ports = parse_ports(self.udp_ports if self.udp_ports else self.udp_port, "udp_port")
        self.tcp_port = tcp_ports[0]
        self.udp_port = udp_ports[0]
        self.tcp_ports = tcp_ports
        self.udp_ports = udp_ports
        if self.default_sni_action == "tls_passthrough" and not self.default_backend_id:
            raise ValueError("default_backend_id is required when default_sni_action is tls_passthrough")
        return self


class ListenerOut(ORMModel, ListenerIn):
    id: int
    created_at: datetime
    updated_at: datetime


class BackendIn(BaseModel):
    name: str
    host: str
    port: int
    protocol: str = "http"
    scheme: Optional[str] = None
    tls_to_backend: bool = False
    send_proxy_protocol: bool = False
    keepalive: int = 32
    read_timeout: int = 3600
    send_timeout: int = 3600
    connect_timeout: int = 60
    preserve_host: bool = True
    forward_real_ip: bool = True
    extra_options: str = "{}"

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return validate_backend_name(value)

    @field_validator("host")
    @classmethod
    def host_valid(cls, value: str) -> str:
        return validate_backend_host(value)

    @field_validator("port")
    @classmethod
    def port_valid(cls, value: int) -> int:
        return validate_port(value)

    @field_validator("protocol")
    @classmethod
    def protocol_valid(cls, value: str) -> str:
        return require_choice(value, BACKEND_PROTOCOLS, "protocol")

    @field_validator("connect_timeout", "read_timeout", "send_timeout")
    @classmethod
    def timeout_valid(cls, value: int) -> int:
        checked = validate_timeout(value)
        assert checked is not None
        return checked


class BackendOut(ORMModel, BackendIn):
    id: int
    created_at: datetime
    updated_at: datetime


class CertificateIn(BaseModel):
    name: str
    domain: str
    cert_path: str
    key_path: str
    managed_by_system: bool = False
    expire_at: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def cert_name_valid(cls, value: str) -> str:
        return validate_backend_name(value)

    @field_validator("domain")
    @classmethod
    def cert_domain_valid(cls, value: str) -> str:
        return validate_domain_list(value, "domain")

    @field_validator("cert_path", "key_path")
    @classmethod
    def file_valid(cls, value: str) -> str:
        return validate_file_path(value)


class CertificateOut(ORMModel, CertificateIn):
    id: int
    created_at: datetime
    updated_at: datetime


class CertificateBulkReplaceIn(BaseModel):
    replace_ids: list[int] = Field(default_factory=list)
    certificates: list[CertificateIn] = Field(min_length=1)


class SniRouteIn(BaseModel):
    listener_id: int = 1
    name: str
    enabled: bool = True
    sni: str
    alpn: Optional[str] = None
    priority: int = 100
    action: str
    backend_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def route_name_valid(cls, value: str) -> str:
        return validate_backend_name(value)

    @field_validator("sni")
    @classmethod
    def sni_valid(cls, value: str) -> str:
        return validate_domain_list(value, "sni")

    @field_validator("action")
    @classmethod
    def action_valid(cls, value: str) -> str:
        return require_choice(value, SNI_ACTIONS, "action")

    @model_validator(mode="after")
    def backend_needed(self) -> "SniRouteIn":
        if self.action == "tls_passthrough" and not self.backend_id:
            raise ValueError("backend_id is required for tls_passthrough SNI routes")
        return self


class SniRouteOut(ORMModel, SniRouteIn):
    id: int
    created_at: datetime
    updated_at: datetime


class HttpRouteIn(BaseModel):
    name: str
    enabled: bool = True
    host: Optional[str] = None
    path: Optional[str] = "/"
    match_type: str = "host_path"
    priority: int = 100
    backend_type: str = "http"
    http_mode: Optional[str] = "normal"
    backend_id: int
    is_default_fallback: bool = False
    extra_options: str = "{}"

    @field_validator("name")
    @classmethod
    def route_name_valid(cls, value: str) -> str:
        return validate_backend_name(value)

    @field_validator("host")
    @classmethod
    def host_valid(cls, value: Optional[str]) -> Optional[str]:
        return validate_domain(value, "host", allow_empty=True)

    @field_validator("path")
    @classmethod
    def path_valid(cls, value: Optional[str]) -> Optional[str]:
        return validate_path(value, "path", allow_empty=True)

    @field_validator("match_type")
    @classmethod
    def match_valid(cls, value: str) -> str:
        return require_choice(value, MATCH_TYPES, "match_type")

    @field_validator("backend_type")
    @classmethod
    def backend_type_valid(cls, value: str) -> str:
        return require_choice(value, BACKEND_TYPES, "backend_type")

    @field_validator("http_mode")
    @classmethod
    def http_mode_valid(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        return require_choice(value, HTTP_MODES, "http_mode")

    @model_validator(mode="after")
    def route_consistency(self) -> "HttpRouteIn":
        if self.match_type in {"host", "host_path"} and not self.host:
            raise ValueError("host is required for host and host_path match types")
        if self.match_type in {"path", "host_path"} and not self.path:
            raise ValueError("path is required for path and host_path match types")
        if self.match_type == "default":
            self.is_default_fallback = True
            if not self.path:
                self.path = "/"
        if self.backend_type == "grpc":
            self.http_mode = None
        elif not self.http_mode:
            self.http_mode = "normal"
        return self


class HttpRouteOut(ORMModel, HttpRouteIn):
    id: int
    created_at: datetime
    updated_at: datetime


class ConfigPreview(BaseModel):
    http: str
    stream: str


class ConfigApplyResult(BaseModel):
    ok: bool
    version: Optional[str] = None
    test_result: str = ""
    error_log: str = ""


class ConfigVersionOut(ORMModel):
    id: int
    version: str
    generated_at: datetime
    status: str
    config_path: str
    test_result: str
    error_log: str
    created_at: datetime
    updated_at: datetime
