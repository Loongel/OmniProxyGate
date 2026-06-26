from __future__ import annotations

import os
import shutil
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
HTTP_CONFIG_DIR = Path(os.getenv("GENERATED_HTTP_DIR", "/generated/http"))
STREAM_CONFIG_DIR = Path(os.getenv("GENERATED_STREAM_DIR", "/generated/stream"))
HTTP_CONFIG_FILE = os.getenv("GENERATED_HTTP_FILE", "gateway-http.conf")
STREAM_CONFIG_FILE = os.getenv("GENERATED_STREAM_FILE", "gateway-stream.conf")
VERSIONS_DIR = Path(os.getenv("CONFIG_VERSIONS_DIR", str(DATA_DIR / "versions")))
LOG_DIR = Path(os.getenv("LOG_DIR", str(DATA_DIR / "logs")))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
NGINX_CONTAINER = os.getenv("NGINX_CONTAINER", "")
NGINX_CONTAINER_FILTER = os.getenv("NGINX_CONTAINER_FILTER", "")
USE_DOCKER_CLI = os.getenv("USE_DOCKER_CLI", "true").lower() == "true"
NGINX_TEST_COMMAND = os.getenv("NGINX_TEST_COMMAND", "nginx -t")
NGINX_RELOAD_COMMAND = os.getenv("NGINX_RELOAD_COMMAND", "nginx -s reload")


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int

    @property
    def combined(self) -> str:
        return "\n".join(part for part in [self.stdout, self.stderr] if part).strip()


@dataclass
class ApplyOutcome:
    ok: bool
    version: Optional[str]
    test_result: str
    error_log: str
    path: Optional[Path] = None


def _run_shell(command: str, timeout: int = 30) -> CommandResult:
    if DRY_RUN:
        return CommandResult(ok=True, stdout=f"DRY_RUN: {command}", stderr="", returncode=0)
    completed = subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        ok=completed.returncode == 0,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
        returncode=completed.returncode,
    )


def _resolve_nginx_container() -> str:
    if NGINX_CONTAINER:
        return NGINX_CONTAINER
    if not NGINX_CONTAINER_FILTER:
        return ""
    result = _run_shell(f"docker ps --filter {shlex.quote(NGINX_CONTAINER_FILTER)} --format '{{{{.Names}}}}' | head -n 1", timeout=10)
    if not result.ok:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _nginx_command(base_command: str) -> str:
    if USE_DOCKER_CLI:
        container = _resolve_nginx_container()
        if container:
            return f"docker exec {shlex.quote(container)} {base_command}"
    return base_command


def nginx_test() -> CommandResult:
    return _run_shell(_nginx_command(NGINX_TEST_COMMAND), timeout=45)


def nginx_reload() -> CommandResult:
    return _run_shell(_nginx_command(NGINX_RELOAD_COMMAND), timeout=45)


def ensure_dirs() -> None:
    for path in [HTTP_CONFIG_DIR, STREAM_CONFIG_DIR, VERSIONS_DIR, LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def active_http_path() -> Path:
    return HTTP_CONFIG_DIR / HTTP_CONFIG_FILE


def active_stream_path() -> Path:
    return STREAM_CONFIG_DIR / STREAM_CONFIG_FILE


def save_version_files(version: str, http_conf: str, stream_conf: str) -> Path:
    ensure_dirs()
    version_dir = VERSIONS_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / HTTP_CONFIG_FILE).write_text(http_conf, encoding="utf-8")
    (version_dir / STREAM_CONFIG_FILE).write_text(stream_conf, encoding="utf-8")
    return version_dir


def write_active_configs(http_conf: str, stream_conf: str) -> None:
    ensure_dirs()
    active_http_path().write_text(http_conf, encoding="utf-8")
    active_stream_path().write_text(stream_conf, encoding="utf-8")


def read_active_configs() -> tuple[str, str]:
    http = active_http_path().read_text(encoding="utf-8") if active_http_path().exists() else ""
    stream = active_stream_path().read_text(encoding="utf-8") if active_stream_path().exists() else ""
    return http, stream


def apply_configs(http_conf: str, stream_conf: str) -> ApplyOutcome:
    ensure_dirs()
    version = datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S%f")
    version_dir = save_version_files(version, http_conf, stream_conf)
    old_http, old_stream = read_active_configs()
    write_active_configs(http_conf, stream_conf)

    test = nginx_test()
    if not test.ok:
        write_active_configs(old_http, old_stream)
        return ApplyOutcome(
            ok=False,
            version=version,
            test_result=test.combined,
            error_log="nginx -t failed; restored previous active files.",
            path=version_dir,
        )

    reload_result = nginx_reload()
    if not reload_result.ok:
        write_active_configs(old_http, old_stream)
        # Try to reload the known-good configuration back into nginx.
        rollback_reload = nginx_reload()
        error_log = "reload failed; restored previous active files."
        if rollback_reload.combined:
            error_log += " Rollback reload output: " + rollback_reload.combined
        return ApplyOutcome(
            ok=False,
            version=version,
            test_result=test.combined,
            error_log=error_log + " " + reload_result.combined,
            path=version_dir,
        )

    return ApplyOutcome(
        ok=True,
        version=version,
        test_result="\n".join(x for x in [test.combined, reload_result.combined] if x),
        error_log="",
        path=version_dir,
    )


def rollback_to(version_path: str | Path) -> ApplyOutcome:
    ensure_dirs()
    path = Path(version_path)
    http_file = path / HTTP_CONFIG_FILE
    stream_file = path / STREAM_CONFIG_FILE
    if not http_file.exists() or not stream_file.exists():
        return ApplyOutcome(ok=False, version=None, test_result="", error_log="version files not found", path=path)
    old_http, old_stream = read_active_configs()
    http_conf = http_file.read_text(encoding="utf-8")
    stream_conf = stream_file.read_text(encoding="utf-8")
    write_active_configs(http_conf, stream_conf)
    test = nginx_test()
    if not test.ok:
        write_active_configs(old_http, old_stream)
        return ApplyOutcome(ok=False, version=path.name, test_result=test.combined, error_log="rollback nginx -t failed; restored previous active files", path=path)
    reload_result = nginx_reload()
    if not reload_result.ok:
        write_active_configs(old_http, old_stream)
        nginx_reload()
        return ApplyOutcome(ok=False, version=path.name, test_result=test.combined, error_log="rollback reload failed; restored previous active files. " + reload_result.combined, path=path)
    return ApplyOutcome(ok=True, version=path.name, test_result="\n".join(x for x in [test.combined, reload_result.combined] if x), error_log="", path=path)


def tail_log(name: str = "error.log", lines: int = 300) -> str:
    safe_name = Path(name).name
    log_path = LOG_DIR / safe_name
    if not log_path.exists():
        return ""
    data = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-max(1, min(lines, 5000)):])


def copy_project_sample_if_empty(sample_http: str, sample_stream: str) -> None:
    ensure_dirs()
    if not active_http_path().exists():
        active_http_path().write_text(sample_http, encoding="utf-8")
    if not active_stream_path().exists():
        active_stream_path().write_text(sample_stream, encoding="utf-8")
