"""Local OpenCode TUI session metadata for the desktop workspace.

Only session metadata is read: identifier, title, working directory, agent and
timestamps. Message content, transcripts, credentials and provider settings are
never read, copied or published. Every call uses the OpenCode CLI with an
explicit argument vector; no shell is involved and no file is written.

The list is a local observation, not a claim of coverage: OpenCode decides which
sessions exist, and Taskrivet cannot see sessions held by another account, a
remote host, or a build that stores sessions elsewhere.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

DEFAULT_LIMIT = 60
DEFAULT_PROJECTS = 12
MAX_LIMIT = 500
MAX_TITLE = 200
COMMAND_TIMEOUT = 30

Runner = Callable[[Sequence[str], str | None], Any]


class OpenCodeUnavailable(RuntimeError):
    """The OpenCode CLI could not be reached or returned nothing usable."""


def _default_runner(args: Sequence[str], cwd: str | None = None) -> Any:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
        check=False,
    )


def candidate_executables() -> list[str]:
    """Known local OpenCode binaries, most specific first. Never executed here."""
    candidates: list[str] = []
    found = shutil.which("opencode")
    if found:
        candidates.append(found)
    candidates += [
        "/opt/homebrew/bin/opencode",
        "/usr/local/bin/opencode",
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
        str(Path.home() / ".bun" / "bin" / "opencode"),
    ]
    return [c for c in dict.fromkeys(candidates) if c and os.path.isfile(c) and os.access(c, os.X_OK)]


def executable() -> str | None:
    for candidate in candidate_executables():
        return candidate
    return None


def parse_json(raw: str) -> Any:
    """Tolerant JSON reader: the CLI prints JSON on stdout and logs on stderr."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(text):
        if char in "[{":
            try:
                return json.loads(text[index:])
            except json.JSONDecodeError:
                continue
    return None


def _plain_directory(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("file://"):
        text = text[len("file://") :]
    return text or None


def _milliseconds(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def normalize(raw: Any, fallback_directory: str | None = None) -> dict[str, Any] | None:
    """Reduce one API session record to the metadata Taskrivet is allowed to keep."""
    if not isinstance(raw, dict):
        return None
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    times = raw.get("time") if isinstance(raw.get("time"), dict) else {}
    model = raw.get("model")
    model_id = model.get("id") if isinstance(model, dict) else model
    title = raw.get("title") or raw.get("slug") or ""
    title = " ".join(str(title).split())[:MAX_TITLE]
    directory = (
        _plain_directory(location.get("directory"))
        or _plain_directory(raw.get("directory"))
        or fallback_directory
        or ""
    )
    return {
        "id": identifier.strip(),
        "title": title,
        "directory": directory,
        "directory_available": bool(directory) and Path(directory).is_dir(),
        "project": str(raw.get("projectID") or raw.get("projectId") or ""),
        "created": _milliseconds(times.get("created") or raw.get("created")),
        "updated": _milliseconds(times.get("updated") or raw.get("updated")),
        "agent": str(raw.get("agent") or ""),
        "model": str(model_id or ""),
    }


def _directories(exe: str, runner: Runner, project: str | None, max_projects: int) -> list[str]:
    """Working folders that may own OpenCode sessions."""
    if project:
        return [project]
    try:
        result = runner([exe, "api", "project.list"], None)
    except (OSError, subprocess.SubprocessError):
        return []
    data = parse_json(getattr(result, "stdout", "") or "")
    rows: list[tuple[int, str]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            directory = (
                _plain_directory(item.get("canonical"))
                or _plain_directory(item.get("worktree"))
                or _plain_directory(item.get("directory"))
            )
            if not directory:
                continue
            times = item.get("time") if isinstance(item.get("time"), dict) else {}
            rows.append((_milliseconds(times.get("active") or times.get("updated")), directory))
    if not rows:
        return [str(Path.cwd())]
    rows.sort(key=lambda row: row[0], reverse=True)
    seen: list[str] = []
    for _, directory in rows[: max(1, max_projects)]:
        if directory in seen or not Path(directory).is_dir():
            continue
        seen.append(directory)
    return seen or [str(Path.cwd())]


def _sessions_from_api(exe: str, runner: Runner, directory: str, limit: int) -> list[dict[str, Any]]:
    result = runner(
        [exe, "api", "session.list", "--param", f"directory={directory}", "--param", f"limit={limit}"],
        None,
    )
    data = parse_json(getattr(result, "stdout", "") or "")
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise OpenCodeUnavailable("OpenCode returned no session list.")
    sessions = [normalize(raw, directory) for raw in rows]
    return [item for item in sessions if item]


def _sessions_from_cli(exe: str, runner: Runner, directory: str, limit: int) -> list[dict[str, Any]]:
    result = runner([exe, "session", "list", "--format", "json", "--max-count", str(limit)], directory)
    data = parse_json(getattr(result, "stdout", "") or "")
    if not isinstance(data, list):
        raise OpenCodeUnavailable("OpenCode returned no session list.")
    sessions = [normalize(raw, directory) for raw in data]
    return [item for item in sessions if item]


def _sessions_for(exe: str, runner: Runner, directory: str, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    """Session metadata for one working folder, with a CLI fallback."""
    try:
        return _sessions_from_api(exe, runner, directory, limit), None
    except OpenCodeUnavailable:
        pass
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return _sessions_from_cli(exe, runner, directory, limit), None
    except OpenCodeUnavailable as exc:
        return [], str(exc)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], str(exc)


def discover(
    limit: int = DEFAULT_LIMIT,
    project: str | None = None,
    max_projects: int = DEFAULT_PROJECTS,
    runner: Runner | None = None,
    exe: str | None = None,
) -> dict[str, Any]:
    """List local OpenCode TUI sessions as bounded metadata."""
    observed_at = time.time()
    limit = max(1, min(int(limit), MAX_LIMIT))
    run = runner or _default_runner
    binary = exe or executable()
    if not binary:
        return {
            "available": False,
            "reason": "OpenCode was not found on PATH or in the usual local install folders.",
            "observed_at": observed_at,
            "sessions": [],
            "session_count": 0,
            "projects": [],
            "scope": "Local OpenCode session metadata only. No transcripts, messages, or credentials are read.",
        }

    directories = _directories(binary, run, project, max(1, int(max_projects)))
    collected: list[dict[str, Any]] = []
    problems: list[str] = []

    def collect(directory: str) -> tuple[str, list[dict[str, Any]], str | None]:
        sessions, error = _sessions_for(binary, run, directory, limit)
        return directory, sessions, error

    if len(directories) > 1:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(collect, directories))
    else:
        results = [collect(directory) for directory in directories]

    seen: set[str] = set()
    for directory, sessions, error in results:
        if error:
            problems.append(f"{directory}: {error}")
        for session in sessions:
            if session["id"] in seen:
                continue
            seen.add(session["id"])
            collected.append(session)

    collected.sort(key=lambda item: (item["updated"], item["created"]), reverse=True)
    truncated = len(collected) > limit
    collected = collected[:limit]

    version = ""
    try:
        result = run([binary, "--version"], None)
        version = (getattr(result, "stdout", "") or "").strip().splitlines()[0][:120]
    except (OSError, subprocess.SubprocessError, IndexError):
        version = ""

    return {
        "available": True,
        "observed_at": observed_at,
        "opencode": {"executable": binary, "version": version},
        "projects": [{"directory": directory} for directory in directories],
        "sessions": collected,
        "session_count": len(collected),
        "truncated": truncated,
        "problems": problems,
        "scope": "Local OpenCode session metadata only. No transcripts, messages, or credentials are read.",
        "limitations": [
            "Sessions held by another account, another machine, or a remote host are not visible.",
            "A listed session is an observed record, not proof that a task is progressing.",
        ],
    }
