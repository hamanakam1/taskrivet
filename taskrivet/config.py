"""Private local settings: ticket-service origin, handback adapter, launchers.

Deployment details that never belong in a public repository live here. The
file must be a regular file owned by the current user with mode 0600. It is
not a credential store; keep tokens and keys out of it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
from urllib.parse import quote, urlsplit

from .dashboard import local_origin

NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+@-]{0,127}$")
SETTINGS = {"ticket_service", "ticket_adapter", "launchers", "workdir", "runs_dir"}


def home() -> Path:
    return Path.home() / ".taskrivet"


def config_path() -> Path:
    raw = os.environ.get("TASKRIVET_CONFIG")
    return Path(raw).expanduser() if raw else home() / "config.json"


def runs_root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("runs_dir") or home() / "runs").expanduser()


def private_directory(path: str | Path) -> Path:
    path = Path(path).expanduser()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError(f"{path} must be a folder owned by you with mode 0700")
    return path


def write_private(path: str | Path, text: str, mode: int = 0o600) -> Path:
    """Atomically replace a file that only the current user can read."""
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise
    return path


def _private_file(path: Path) -> None:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError(f"{path} must be a regular file owned by you with mode 0600")


def load(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path).expanduser() if path else config_path()
    try:
        _private_file(path)
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ValueError(f"{path} is not valid JSON") from None
    return validate(data)


def _absolute(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value or len(value) > 4096:
        raise ValueError(f"{label} must be a path")
    if not Path(value).expanduser().is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return value


def _argv(value: Any, label: str) -> list[str]:
    if (not isinstance(value, list) or not 1 <= len(value) <= 64
            or any(not isinstance(x, str) or "\0" in x or len(x) > 4096 for x in value)):
        raise ValueError(f"{label} must be a list of 1-64 strings")
    _absolute(value[0], label + "[0]")
    return value


def _seconds(value: Any, label: str) -> None:
    if type(value) not in (int, float) or not 1 <= value <= 600:
        raise ValueError(f"{label} must be 1-600 seconds")


def _table(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = sorted(set(value) - keys)
    if unknown:
        raise ValueError(f"Unknown {label} setting: {', '.join(unknown)}")
    return value


def validate(data: Any) -> dict[str, Any]:
    _table(data, "config", SETTINGS)
    service = data.get("ticket_service")
    if service is not None:
        _table(service, "ticket_service", {"origin", "ticket_url", "timeout"})
        if "origin" in service:
            local_origin(service["origin"])
        if "ticket_url" in service:
            url = service["ticket_url"]
            if not isinstance(url, str) or "{key}" not in url or len(url) > 1024:
                raise ValueError("ticket_service.ticket_url must be a URL template containing {key}")
            parts = urlsplit(url)
            try:
                local_origin(f"{parts.scheme}://{parts.netloc}")
            except ValueError:
                raise ValueError("ticket_service.ticket_url must point at a local HTTP origin") from None
        if "timeout" in service:
            _seconds(service["timeout"], "ticket_service.timeout")
    adapter = data.get("ticket_adapter")
    if adapter is not None:
        _table(adapter, "ticket_adapter", {"argv", "timeout"})
        if "argv" not in adapter:
            raise ValueError("ticket_adapter.argv is required")
        _argv(adapter["argv"], "ticket_adapter.argv")
        if "timeout" in adapter:
            _seconds(adapter["timeout"], "ticket_adapter.timeout")
    launchers = data.get("launchers")
    if launchers is not None:
        if not isinstance(launchers, dict):
            raise ValueError("launchers must be an object keyed by tool name")
        for name, spec in launchers.items():
            if not isinstance(name, str) or not NAME.fullmatch(name):
                raise ValueError(f"Invalid launcher name: {str(name)[:64]!r}")
            _table(spec, f"launchers.{name}", {"argv", "disabled", "label"})
            if "argv" in spec:
                _argv(spec["argv"], f"launchers.{name}.argv")
            if "disabled" in spec and (not isinstance(spec["disabled"], str) or not spec["disabled"].strip()):
                raise ValueError(f"launchers.{name}.disabled must explain why the launcher is disabled")
            if "label" in spec and (not isinstance(spec["label"], str) or len(spec["label"]) > 128):
                raise ValueError(f"launchers.{name}.label must be short text")
            if "argv" not in spec and "disabled" not in spec:
                raise ValueError(f"launchers.{name} needs argv or disabled")
    for key in ("workdir", "runs_dir"):
        if key in data:
            _absolute(data[key], key)
    return data


def save(data: dict[str, Any], path: str | Path | None = None) -> Path:
    validate(data)
    path = Path(path).expanduser() if path else config_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    if path.exists() or path.is_symlink():
        _private_file(path)
    return write_private(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _key(key: Any) -> list[str]:
    parts = key.split(".") if isinstance(key, str) else []
    if not parts or len(parts) > 4 or any(not NAME.fullmatch(p) for p in parts):
        raise ValueError("Use a dotted setting name such as ticket_service.origin")
    return parts


def _parse(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def get_value(key: str, path: str | Path | None = None) -> Any:
    node: Any = load(path)
    for part in _key(key):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"{key} is not set")
        node = node[part]
    return node


def set_value(key: str, raw: str, path: str | Path | None = None) -> dict[str, Any]:
    parts = _key(key)
    data = load(path)
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if child is None:
            child = node[part] = {}
        elif not isinstance(child, dict):
            raise ValueError(f"{part} is not an object")
        node = child
    node[parts[-1]] = _parse(raw)
    save(data, path)
    return data


def unset_value(key: str, path: str | Path | None = None) -> dict[str, Any]:
    parts = _key(key)
    data = load(path)
    trail = [data]
    node: Any = data
    for part in parts[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            raise ValueError(f"{key} is not set")
        trail.append(node)
    if parts[-1] not in node:
        raise ValueError(f"{key} is not set")
    del node[parts[-1]]
    for parent, part in zip(reversed(trail[:-1]), reversed(parts[:-1])):
        if parent[part] == {}:
            del parent[part]
    save(data, path)
    return data


def describe(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path).expanduser() if path else config_path()
    return {
        "path": str(path),
        "exists": path.exists(),
        "settings": load(path),
        "note": "Private local settings. Keep credentials out of this file.",
    }


def ticket_origin(cfg: dict[str, Any], override: str | None = None) -> str:
    origin = override or (cfg.get("ticket_service") or {}).get("origin")
    if not origin:
        raise ValueError(
            "No ticket service configured. Run: taskrivet config set ticket_service.origin http://127.0.0.1:PORT"
        )
    return local_origin(origin)


def ticket_timeout(cfg: dict[str, Any]) -> float:
    return (cfg.get("ticket_service") or {}).get("timeout", 30)


def ticket_link(cfg: dict[str, Any], key: str) -> str | None:
    """Where the operator can open a ticket in a browser, when a template is configured."""
    template = (cfg.get("ticket_service") or {}).get("ticket_url")
    return template.replace("{key}", quote(key, safe="")) if template else None
