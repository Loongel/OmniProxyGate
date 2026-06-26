from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_DOMAIN_RE = re.compile(r"^(\*\.)?(?=.{1,253}$)([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,253}$")
_BACKEND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_SAFE_FILE_RE = re.compile(r"^/[A-Za-z0-9._~+@%/=-]+$")

LISTEN_ADDRESS_MODES = {"unified", "split", "ipv4_only", "ipv6_only"}
SNI_ACTIONS = {"http_termination", "tls_passthrough", "reject"}
BACKEND_PROTOCOLS = {"http", "https", "grpc", "grpcs", "h2c", "tcp_tls"}
BACKEND_TYPES = {"http", "grpc"}
HTTP_MODES = {"normal", "websocket", "xhttp_stream"}
MATCH_TYPES = {"host", "path", "host_path", "default"}


class ValidationError(ValueError):
    pass


def require_choice(value: str, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise ValidationError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return value


def validate_port(port: int, field: str = "port") -> int:
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValidationError(f"{field} must be between 1 and 65535")
    return port


def validate_timeout(seconds: int | None, field: str = "timeout") -> int | None:
    if seconds is None:
        return None
    if not isinstance(seconds, int) or seconds < 1 or seconds > 86400:
        raise ValidationError(f"{field} must be between 1 and 86400 seconds")
    return seconds


def validate_domain(value: str | None, field: str = "domain", allow_empty: bool = False) -> str | None:
    if value is None or value == "":
        if allow_empty:
            return value
        raise ValidationError(f"{field} is required")
    value = value.strip().lower()
    if value == "_":
        return value
    if not _DOMAIN_RE.match(value):
        raise ValidationError(f"{field} must be a valid domain name, optionally prefixed with *.")
    return value


def split_domain_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[\s,，;；]+", value) if part.strip()]


def validate_domain_list(value: str | None, field: str = "domain") -> str:
    domains = split_domain_list(value)
    if not domains:
        raise ValidationError(f"{field} is required")
    checked: list[str] = []
    for domain in domains:
        normalized = validate_domain(domain, field)
        assert normalized is not None
        if normalized not in checked:
            checked.append(normalized)
    return ",".join(checked)


def validate_backend_host(value: str, field: str = "host") -> str:
    value = value.strip()
    if not value:
        raise ValidationError(f"{field} is required")
    try:
        ipaddress.ip_address(value.strip("[]"))
        return value
    except ValueError:
        pass
    if not _HOST_RE.match(value):
        raise ValidationError(f"{field} contains unsupported characters")
    if ".." in value or value.startswith("-") or value.endswith("-"):
        raise ValidationError(f"{field} is not a valid backend host")
    return value


def validate_backend_name(value: str, field: str = "name") -> str:
    value = value.strip()
    if not _BACKEND_NAME_RE.match(value):
        raise ValidationError(f"{field} must start with a letter or digit and contain only letters, digits, dot, dash, underscore")
    return value


def validate_path(value: str | None, field: str = "path", allow_empty: bool = False) -> str | None:
    if value is None or value == "":
        if allow_empty:
            return value
        raise ValidationError(f"{field} is required")
    value = value.strip()
    if not _PATH_RE.match(value):
        raise ValidationError(f"{field} must start with / and contain only URL-safe path characters")
    if "//" in value and value != "/":
        raise ValidationError(f"{field} cannot contain //")
    return value


def validate_file_path(value: str, field: str = "path") -> str:
    value = value.strip()
    if not value.startswith("/") or not _SAFE_FILE_RE.match(value):
        raise ValidationError(f"{field} must be an absolute safe file path")
    if "/../" in value or value.endswith("/.."):
        raise ValidationError(f"{field} cannot traverse directories")
    return value


def validate_urlish(value: str, field: str = "url") -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https", "grpc", "grpcs"}:
        raise ValidationError(f"{field} has unsupported scheme")
    if not parts.hostname:
        raise ValidationError(f"{field} must include host")
    return value
