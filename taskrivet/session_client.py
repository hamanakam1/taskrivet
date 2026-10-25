"""Client for the per-ledger terminal session service.

Finds the service the desktop app uses for the same ledger, or starts the
standard-library one in ``taskrivet.sessiond`` when none is running. A lost
connection or a timeout leaves a request's outcome unknown; list terminals
again before retrying anything that creates or writes.
"""
from __future__ import annotations

import codecs
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, BinaryIO, TextIO

from .sessiond import MAX_FRAME, VERSION, private_directory, read_token

# Run-scoped variables must not leak into a service that outlives the run.
SCRUBBED = frozenset({"TASKRIVET_SESSION", "TASKRIVET_TASK", "TASKRIVET_CONTEXT",
                      "TASKRIVET_TICKET", "TASKRIVET_RUN", "ELECTRON_RUN_AS_NODE"})
DETACH = b"\x1d"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
LOST = "Session connection lost; command outcome unknown. List terminals before retrying."
TIMED_OUT = "Session request timed out; outcome unknown, do not blindly retry."
UNREACHABLE = (FileNotFoundError, ConnectionRefusedError)


class SessionError(OSError):
    """The session service could not be reached, or an outcome is unknown."""


class ServiceNotRunning(SessionError):
    """No session service is listening for this ledger."""


class RequestRefused(ValueError):
    """The service answered and refused the request."""


def session_dir(db: str | Path) -> Path:
    """Same folder the desktop app derives from the ledger path."""
    override = os.environ.get("TASKRIVET_SESSION_DIR")
    if override:
        return Path(override).expanduser()
    resolved = os.path.abspath(os.path.expanduser(str(db)))
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".taskrivet" / ("sessions-" + digest)


def ensure_token(directory: Path) -> str:
    path = directory / "token"
    if not os.path.lexists(path):
        fd, temp = tempfile.mkstemp(dir=directory, prefix=".token.")
        try:
            os.write(fd, secrets.token_hex(32).encode())
            os.close(fd)
            fd = -1
            try:
                os.link(temp, path)
            except FileExistsError:
                pass
        finally:
            if fd >= 0:
                os.close(fd)
            os.unlink(temp)
    return read_token(directory)


def summarize(t: dict[str, Any]) -> dict[str, Any]:
    """A terminal record without its scrollback."""
    chunks = [c for c in t.get("chunks") or [] if isinstance(c, dict)]
    tail = ANSI.sub("", "".join(str(c.get("data", "")) for c in chunks[-4:]))
    lines = [line.strip() for line in tail.replace("\r", "\n").split("\n") if line.strip()]
    return {
        "id": t.get("id"),
        "title": t.get("title"),
        "kind": t.get("kind"),
        "ref": t.get("ref"),
        "task": t.get("task"),
        "session": t.get("session"),
        "state": t.get("state"),
        "exit_code": t.get("exitCode"),
        "pid": t.get("pid"),
        "cwd": t.get("cwd"),
        "command": Path(str(t.get("shell") or "")).name or None,
        "output_bytes": sum(len(str(c.get("data", "")).encode("utf-8")) for c in chunks),
        "last_line": lines[-1][:160] if lines else None,
    }


def find_terminal(terminals: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
    for t in terminals:
        if t.get("id") == wanted:
            return t
    matches = [t for t in terminals if len(wanted) >= 4 and str(t.get("id", "")).startswith(wanted)]
    if len(matches) > 1:
        raise ValueError("Terminal id prefix matches more than one terminal")
    if not matches:
        raise ValueError("No terminal with that id. Run: taskrivet sessions")
    return matches[0]


class SessionClient:
    def __init__(self, directory: str | Path, timeout: float = 10.0) -> None:
        self.dir = Path(directory)
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.buffer = bytearray()
        self.events: collections.deque[dict[str, Any]] = collections.deque(maxlen=100_000)
        self.next_id = 0
        self.hello: dict[str, Any] | None = None

    @property
    def socket_path(self) -> Path:
        return self.dir / "sessions.sock"

    @property
    def log_path(self) -> Path:
        return self.dir / "service.log"

    def __enter__(self) -> "SessionClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        sock, self.sock = self.sock, None
        if sock is not None:
            sock.close()
        self.buffer.clear()

    # -- connection --------------------------------------------------------
    def connect(self, start: bool = True) -> dict[str, Any]:
        if self.sock is not None and self.hello is not None:
            return self.hello
        if not start and not os.path.lexists(self.socket_path):
            raise ServiceNotRunning("Session service is not running")
        private_directory(self.dir)
        token = ensure_token(self.dir)
        try:
            return self._attach(token)
        except UNREACHABLE:
            if not start:
                raise ServiceNotRunning("Session service is not running (stale socket)") from None
        lock = self.dir / "starting"
        try:
            os.mkdir(lock, 0o700)
        except FileExistsError:
            return self._wait(token)
        try:
            # Recheck under the startup lock; never unlink a live socket.
            try:
                return self._attach(token)
            except UNREACHABLE:
                pass
            self._clear_stale_socket()
            self._spawn()
            return self._wait(token)
        finally:
            os.rmdir(lock)

    def _attach(self, token: str) -> dict[str, Any]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.socket_path))
        except BaseException:
            sock.close()
            raise
        self.close()
        self.sock = sock
        try:
            hello = self.request("hello", None, {"token": token, "version": VERSION})
        except SessionError:
            self.close()
            raise SessionError(
                "Session service refused the handshake; its token no longer matches."
                " Stop that service before retrying.") from None
        except BaseException:
            self.close()
            raise
        if not isinstance(hello, dict) or hello.get("version") != VERSION:
            self.close()
            raise SessionError("Session service speaks an unsupported protocol version")
        self.hello = hello
        return hello

    def _wait(self, token: str, attempts: int = 100) -> dict[str, Any]:
        for _ in range(attempts):
            try:
                return self._attach(token)
            except UNREACHABLE:
                time.sleep(0.1)
        raise SessionError(
            "Session service unavailable. A stale startup lock may require operator reconciliation."
            f" Existing commands were not replayed. Service log: {self.log_path}")

    def _clear_stale_socket(self) -> None:
        try:
            st = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
            raise SessionError("Unsafe session socket; refusing to replace it")
        os.unlink(self.socket_path)

    def _spawn(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        script = Path(__file__).resolve().with_name("sessiond.py")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            if os.lstat(self.log_path).st_size > 1_000_000:
                flags |= os.O_TRUNC
        except FileNotFoundError:
            pass
        log = os.open(self.log_path, flags, 0o600)
        try:
            # -I keeps the service on the standard library alone; it imports nothing else.
            done = subprocess.run(
                [sys.executable, "-I", str(script), "--detach", str(self.dir)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                cwd="/", env=env, start_new_session=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SessionError(f"Session service could not start: {exc}") from None
        finally:
            os.close(log)
        if done.returncode != 0:
            raise SessionError(f"Session service failed to start; see {self.log_path}")

    # -- messages ----------------------------------------------------------
    def request(self, op: str, data: dict[str, Any] | None = None,
                extra: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        if self.sock is None:
            raise SessionError("Session service disconnected")
        self.next_id += 1
        rid = self.next_id
        message: dict[str, Any] = {"id": rid, "op": op, "data": data or {}}
        message.update(extra or {})
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self.sock.settimeout(self.timeout)
            self.sock.sendall(line)
        except OSError:
            self.close()
            raise SessionError(LOST) from None
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            reply = self._next(deadline)
            if "event" in reply:
                self.events.append(reply)
                continue
            if reply.get("id") != rid:
                continue
            if "error" in reply:
                raise RequestRefused(str(reply.get("error"))[:500])
            return reply.get("result")

    def call(self, op: str, data: dict[str, Any] | None = None) -> Any:
        self.connect()
        return self.request(op, data)

    def pump(self) -> None:
        """Read what the socket has now and queue any events."""
        self._fill(self.timeout)
        while (message := self._parse()) is not None:
            if "event" in message:
                self.events.append(message)

    def _next(self, deadline: float) -> dict[str, Any]:
        while True:
            message = self._parse()
            if message is not None:
                return message
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise SessionError(TIMED_OUT)
            self._fill(wait)

    def _parse(self) -> dict[str, Any] | None:
        end = self.buffer.find(b"\n")
        if end < 0:
            return None
        raw = bytes(self.buffer[:end])
        del self.buffer[:end + 1]
        try:
            message = json.loads(raw)
        except ValueError:
            message = None
        if not isinstance(message, dict):
            self.close()
            raise SessionError("Session service sent malformed data; connection closed")
        return message

    def _fill(self, wait: float) -> None:
        if self.sock is None:
            raise SessionError("Session service disconnected")
        try:
            self.sock.settimeout(max(wait, 0.001))
            chunk = self.sock.recv(1 << 20)
        except TimeoutError:
            raise SessionError(TIMED_OUT) from None
        except OSError:
            self.close()
            raise SessionError(LOST) from None
        if not chunk:
            self.close()
            raise SessionError(LOST)
        self.buffer += chunk
        if len(self.buffer) > MAX_FRAME:
            self.close()
            raise SessionError("Session message exceeds the frame limit; connection closed")


def attach(
    client: SessionClient,
    terminal_id: str,
    *,
    follow: bool = True,
    interactive: bool | None = None,
    out: BinaryIO | None = None,
    err: TextIO | None = None,
    stdin_fd: int | None = None,
) -> dict[str, Any]:
    """Replay a terminal's scrollback, then stream it until exit or Ctrl-].

    Detaching leaves the terminal running in the service.
    """
    out = out if out is not None else sys.stdout.buffer
    err = err if err is not None else sys.stderr
    t = find_terminal(client.request("list") or [], terminal_id)
    tid = t["id"]
    last = 0
    for chunk in t.get("chunks") or []:
        out.write(str(chunk.get("data", "")).encode("utf-8", "replace"))
        last = max(last, int(chunk.get("seq") or 0))
    out.flush()
    if t.get("state") != "running":
        return {"id": tid, "state": t.get("state"), "exit_code": t.get("exitCode"), "detached": False}
    if not follow:
        return {"id": tid, "state": "running", "exit_code": None, "detached": True}
    if stdin_fd is None:
        try:
            stdin_fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            stdin_fd = -1
    if interactive is None:
        interactive = stdin_fd >= 0 and os.isatty(stdin_fd)
    saved = None
    previous = None
    resized = [interactive]
    selector = selectors.DefaultSelector()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def done(state: str, code: Any, detached: bool) -> dict[str, Any]:
        return {"id": tid, "state": state, "exit_code": code, "detached": detached}

    try:
        if interactive:
            import termios
            import tty
            saved = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd)
            previous = signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
            err.write("[attached; Ctrl-] detaches and leaves the terminal running]\r\n")
            err.flush()
            selector.register(stdin_fd, selectors.EVENT_READ, "stdin")
        assert client.sock is not None
        selector.register(client.sock, selectors.EVENT_READ, "socket")
        while True:
            while client.events:
                message = client.events.popleft()
                payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
                if payload.get("id") != tid:
                    continue
                if message.get("event") == "terminal:data" and int(payload.get("seq") or 0) > last:
                    last = int(payload["seq"])
                    out.write(str(payload.get("data", "")).encode("utf-8", "replace"))
                    out.flush()
                elif message.get("event") == "terminal:exit":
                    return done("exited", payload.get("exitCode"), False)
            if resized[0]:
                resized[0] = False
                try:
                    cols, rows = os.get_terminal_size(stdin_fd)
                    client.request("resize", {"id": tid, "cols": max(2, min(cols, 500)), "rows": max(1, min(rows, 300))})
                except (OSError, RequestRefused):
                    pass
                continue
            for key, _ in selector.select(0.25):
                if key.data == "socket":
                    client.pump()
                    continue
                data = os.read(stdin_fd, 4096)
                if not data:
                    selector.unregister(stdin_fd)
                    continue
                before, cut, _rest = data.partition(DETACH)
                text = decoder.decode(before)
                if text:
                    client.request("write", {"id": tid, "text": text})
                if cut:
                    return done("running", None, True)
    except KeyboardInterrupt:
        return done("running", None, True)
    finally:
        selector.close()
        if saved is not None:
            import termios
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved)
        if previous is not None:
            signal.signal(signal.SIGWINCH, previous)
