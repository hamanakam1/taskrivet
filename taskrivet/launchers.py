"""How each known agent CLI takes an initial interactive prompt.

Profiles come from each tool's own --help output. A tool without a verified
prompt option launches with no arguments; the context path still reaches it
through TASKRIVET_CONTEXT and the run folder. Private wrappers belong in the
local config file, not here.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from .tools import AGENTS, SAFE_NAME, inventory

PROFILES: dict[str, list[str]] = {
    "claude": ["{prompt}"],
    "codex": ["{prompt}"],
    "droid": ["{prompt}"],
    "cursor-agent": ["{prompt}"],
    "cline": ["{prompt}"],
    "grok": ["{prompt}"],
    "vibe": ["{prompt}"],
    "qodercli": ["{prompt}"],
    "copilot": ["-i", "{prompt}"],
    "gemini": ["-i", "{prompt}"],
    "opencode": ["--prompt", "{prompt}"],
    "kilo": ["--prompt", "{prompt}"],
}
PLACEHOLDER = re.compile(r"\{(prompt|context)\}")


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve(tool: str, cfg: dict[str, Any], paths: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(tool, str) or not SAFE_NAME.fullmatch(tool):
        raise ValueError("Tool name must be a plain executable name such as codex")
    custom = (cfg.get("launchers") or {}).get(tool) or {}
    if custom.get("disabled"):
        raise ValueError(f"Launcher {tool} is disabled in local config: {custom['disabled']}")
    if custom.get("argv"):
        argv = [str(Path(custom["argv"][0]).expanduser())] + list(custom["argv"][1:])
        if not _executable(argv[0]):
            raise ValueError(f"Configured launcher for {tool} is not an executable file")
        return {
            "tool": tool,
            "label": custom.get("label") or AGENTS.get(tool, tool),
            "argv": argv,
            "source": "local config",
            "prompt": any(PLACEHOLDER.search(a) for a in argv[1:]),
        }
    found = inventory(paths=paths)
    exe = next((t["executable"] for t in found["tools"] if t["id"] == tool and t["installed"]), None)
    if not exe:
        raise ValueError(f"{tool} is not installed in a scanned location. Run: taskrivet tools")
    template = PROFILES.get(tool, [])
    return {
        "tool": tool,
        "label": AGENTS.get(tool, tool),
        "argv": [exe] + template,
        "source": "built-in profile" if tool in PROFILES else "no verified prompt option",
        "prompt": bool(template),
    }


def render(argv: list[str], prompt: str, context: str) -> list[str]:
    values = {"prompt": prompt, "context": context}
    return [argv[0]] + [PLACEHOLDER.sub(lambda m: values[m.group(1)], a) for a in argv[1:]]


def catalog(cfg: dict[str, Any], paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Every launcher the operator could pick. Nothing is executed."""
    custom = cfg.get("launchers") or {}
    installed = {t["id"] for t in inventory(paths=paths)["tools"] if t["installed"]}
    rows = []
    for name in sorted(set(PROFILES) | set(custom)):
        spec = custom.get(name) or {}
        if spec.get("disabled"):
            rows.append({"tool": name, "status": "disabled", "detail": spec["disabled"]})
        elif spec.get("argv"):
            ready = _executable(str(Path(spec["argv"][0]).expanduser()))
            rows.append({"tool": name, "status": "ready" if ready else "missing", "detail": "local config"})
        else:
            rows.append({"tool": name, "status": "ready" if name in installed else "not installed",
                         "detail": "built-in profile"})
    return rows
