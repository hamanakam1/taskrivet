"""Local executable inventory. Never executes discovered commands or reads credentials."""
import os
from pathlib import Path
import re
import time
from typing import Any

AGENTS: dict[str, str] = {
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "gemini-lane": "Gemini configured lane",
    "qwen": "Qwen Code",
    "opencode": "OpenCode",
    "aider": "Aider",
    "goose": "Goose",
    "amp": "Amp",
    "crush": "Crush",
    "droid": "Factory Droid",
    "copilot": "GitHub Copilot CLI",
    "cursor-agent": "Cursor Agent",
    "agent": "Agent (identity requires verification)",
    "kiro-cli": "Kiro CLI",
    "vibe": "Mistral Vibe",
    "cline": "Cline",
    "kilo": "Kilo",
    "qodercli": "Qoder CLI",
    "qoder": "Qoder (identity requires verification)",
    "grok": "Grok",
    "omp": "Oh My Pi",
    "pi": "Pi",
    "openhands": "OpenHands",
    "auggie": "Augment CLI",
    "trae": "Trae (identity requires verification)",
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+@-]{0,127}$")


def directories() -> list[str]:
    home = Path.home()
    extra = [
        ".local/bin",
        ".grok/bin",
        ".qoder/entry",
        ".npm-global/bin",
        ".cargo/bin",
        ".bun/bin",
        ".opencode/bin",
    ]
    paths = os.environ.get("PATH", "").split(os.pathsep)
    paths += [str(home / p) for p in extra] + ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    return list(dict.fromkeys(p for p in paths if p and Path(p).is_absolute()))


def history_counts(path: str | Path, names: set[str], max_bytes: int = 2_000_000) -> dict[str, dict[str, int]]:
    """Only recognize first command names; never return arguments or raw history.

    Extended zsh timestamps allow a 90-day window. Untimestamped entries are
    explicitly a bounded history sample, not proof of recent use. Compound
    commands, aliases and commands in other applications are not inferred.
    """
    counts: dict[str, dict[str, int]] = {}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            if size > max_bytes:
                f.readline()
            lines = f.read(max_bytes).decode("utf-8", "replace").splitlines()
    except OSError:
        return counts

    for line in lines:
        dated = re.match(r"^: (\d+):\d+;(.*)$", line)
        if dated:
            if int(dated[1]) < time.time() - 90 * 86400:
                continue
            line = dated[2]
        match = re.match(r"^\s*([A-Za-z0-9_][A-Za-z0-9_.+@-]*)(?:\s|$)", line)
        if match and match[1] in names:
            item = counts.setdefault(match[1], {"recent_count": 0, "undated_count": 0})
            item["recent_count" if dated else "undated_count"] += 1
    return counts


def inventory(
    include_history: bool = False,
    paths: list[str] | None = None,
    history_path: str | Path | None = None,
) -> dict[str, Any]:
    found: dict[str, str] = {}
    for directory in directories() if paths is None else paths:
        try:
            for entry in Path(directory).iterdir():
                if SAFE_NAME.fullmatch(entry.name) and entry.is_file() and os.access(entry, os.X_OK):
                    found.setdefault(entry.name, str(entry.absolute()))
        except OSError:
            continue
    names = set(found) | set(AGENTS)
    history = history_counts(history_path or Path.home() / ".zsh_history", names) if include_history else {}
    rows = [
        {
            "id": name,
            "name": AGENTS.get(name, name),
            "category": "coding-agent" if name in AGENTS else "cli",
            "executable": found.get(name),
            "installed": name in found,
            "authentication": "unknown",
            "cost": "unknown",
            **history.get(name, {"recent_count": 0, "undated_count": 0}),
        }
        for name in sorted(names)
    ]
    return {
        "observed_at": time.time(),
        "tools": rows,
        "installed": len(found),
        "agent_profiles": len(AGENTS),
        "history_scanned": include_history,
        "history_scope": "Last 2 MB of zsh history; dated entries within 90 days. First commands only.",
        "execution_authorized": False,
    }