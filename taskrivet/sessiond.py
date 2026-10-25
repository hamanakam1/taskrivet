"""Taskrivet's terminal session service, standard library only (macOS and Linux).

Speaks the desktop service's protocol: newline-delimited JSON over a per-ledger
Unix socket in a mode-0700 folder, a mode-0600 handshake token, and the
operations list, create, write, resize, stop and remove, with terminal:data
and terminal:exit events. This process owns the pseudo-terminals, so clients
may disconnect and reattach freely. Terminal state lives in memory only.
"""
from __future__ import annotations

import codecs
import collections
import errno
import fcntl
import hmac
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import struct
import sys
import termios
import time
import traceback
import uuid
from typing import Any

VERSION = 1
MAX_FRAME = 32 * 1024 * 1024
MAX_TABS = 24
MAX_OUTPUT = 1024 * 1024
CHUNK_CHARS = 65536
PAUSE_CHARS = 262144
MAX_INPUT_QUEUE = 1024 * 1024
TICK = 0.016
IDLE = 0.25
HELLO_TIMEOUT = 3.0
ORPHAN_CHECK = 2.0
CHILD_SIGNALS = ("SIGPIPE", "SIGXFSZ", "SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT",
                 "SIGCHLD", "SIGTSTP", "SIGTTIN", "SIGTTOU", "SIGWINCH")


def private_directory(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("Session directory must be owned by you with mode 0700")
    return path


def read_token(directory: str | Path) -> str:
    path = Path(directory) / "token"
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("Unsafe session token")
    return path.read_text(encoding="utf-8")


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise ValueError("Invalid " + label)
    return value


def _dimensions(cols: Any, rows: Any) -> tuple[int, int]:
    if type(cols) is not int or type(rows) is not int or not 2 <= cols <= 500 or not 1 <= rows <= 300:
        raise ValueError("Invalid terminal dimensions")
    return cols, rows


def _directory(value: Any) -> str:
    _text(value, "working directory", 4096)
    resolved = os.path.realpath(value)
    if not os.path.isdir(resolved):
        raise ValueError("Working directory is not a folder")
    return resolved


def _set_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Terminal:
    def __init__(self, pid: int, fd: int, cwd: str, shell: str, data: dict[str, Any]) -> None:
        self.id = str(uuid.uuid4())
        self.pid = pid
        self.fd: int | None = fd
        self.cwd = cwd
        self.shell = shell
        self.task = data.get("task") or None
        self.session = data.get("session") or None
        self.title = data.get("title") or None
        self.kind = data.get("kind") or "shell"
        self.ref = data.get("ref") or None
        self.state = "running"
        self.exit_code: int | None = None
        self.chunks: collections.deque[tuple[dict[str, Any], int]] = collections.deque()
        self.bytes = 0
        self.seq = 0
        self.pending = ""
        self.paused = False
        self.eof = False
        self.inbox = bytearray()
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.flushed = 0.0
        self.mask = 0

    def snapshot(self) -> dict[str, Any]:
        view = {"id": self.id, "cwd": self.cwd, "task": self.task, "session": self.session,
                "shell": self.shell, "state": self.state, "chunks": [c for c, _ in self.chunks],
                "pid": self.pid, "title": self.title, "kind": self.kind, "ref": self.ref}
        if self.exit_code is not None:
            view["exitCode"] = self.exit_code
        return view


class Client:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.inbuf = bytearray()
        self.outbuf = bytearray()
        self.authenticated = False
        self.deadline = time.monotonic() + HELLO_TIMEOUT
        self.closed = False
        self.mask = selectors.EVENT_READ


class Service:
    def __init__(self, directory: str | Path, token: str) -> None:
        self.dir = private_directory(directory)
        self.token = token
        self.socket_path = str(self.dir / "sessions.sock")
        self.selector = selectors.DefaultSelector()
        self.terminals: dict[str, Terminal] = {}
        self.clients: set[Client] = set()
        self.server: socket.socket | None = None
        self.inode: int | None = None
        self.running = True
        self.checked = time.monotonic()

    # -- lifecycle ---------------------------------------------------------
    def listen(self) -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous = os.umask(0o177)
        try:
            server.bind(self.socket_path)
        finally:
            os.umask(previous)
        os.chmod(self.socket_path, 0o600)
        self.inode = os.stat(self.socket_path).st_ino
        server.listen(16)
        server.setblocking(False)
        self.server = server
        self.selector.register(server, selectors.EVENT_READ, ("server", None))

    def serve(self) -> None:
        while self.running:
            busy = any(t.pending or (t.state == "running" and t.eof) for t in self.terminals.values())
            for key, events in self.selector.select(TICK if busy else IDLE):
                kind, obj = key.data
                try:
                    if kind == "server":
                        self._accept()
                    elif kind == "client":
                        self._client_io(obj, events)
                    else:
                        self._terminal_io(obj, events)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    if kind == "client":
                        self._drop(obj)
            try:
                self._tick()
            except Exception:
                traceback.print_exc(file=sys.stderr)
        self.close()

    def close(self) -> None:
        for t in self.terminals.values():
            if t.state == "running":
                self._hangup(t)
        for client in list(self.clients):
            self._drop(client)
        if self.server is not None:
            try:
                self.selector.unregister(self.server)
            except (KeyError, ValueError):
                pass
            self.server.close()
            self.server = None
            try:
                if os.stat(self.socket_path).st_ino == self.inode:
                    os.unlink(self.socket_path)
            except OSError:
                pass
        for t in self.terminals.values():
            if t.fd is not None:
                try:
                    os.close(t.fd)
                except OSError:
                    pass
                t.fd = None
        self.selector.close()

    def _orphaned(self) -> bool:
        try:
            return os.stat(self.socket_path).st_ino != self.inode
        except OSError:
            return True

    def _tick(self) -> None:
        now = time.monotonic()
        if now - self.checked >= ORPHAN_CHECK:
            self.checked = now
            if self.server is not None and self._orphaned():
                # The socket was removed or replaced, so no new client can reach this service.
                self.selector.unregister(self.server)
                self.server.close()
                self.server = None
            if self.server is None and not any(t.state == "running" for t in self.terminals.values()):
                self.running = False
        for client in list(self.clients):
            if not client.authenticated and now > client.deadline:
                self._drop(client)
        for t in list(self.terminals.values()):
            if t.pending and (len(t.pending) >= CHUNK_CHARS or now - t.flushed >= TICK):
                self._flush(t)
            if t.state == "running":
                self._reap(t)

    # -- terminals ---------------------------------------------------------
    def _watch(self, t: Terminal) -> None:
        mask = 0
        if t.state == "running" and t.fd is not None and not t.eof:
            if not t.paused:
                mask |= selectors.EVENT_READ
            if t.inbox:
                mask |= selectors.EVENT_WRITE
        if mask == t.mask:
            return
        if t.mask and mask:
            self.selector.modify(t.fd, mask, ("terminal", t))
        elif mask:
            self.selector.register(t.fd, mask, ("terminal", t))
        else:
            self.selector.unregister(t.fd)
        t.mask = mask

    def _terminal_io(self, t: Terminal, events: int) -> None:
        if events & selectors.EVENT_READ:
            self._read(t)
        if events & selectors.EVENT_WRITE and t.state == "running" and not t.eof:
            self._write_input(t)

    def _read(self, t: Terminal) -> None:
        try:
            data = os.read(t.fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            t.eof = True
            self._watch(t)
            self._reap(t)
            return
        t.pending += t.decoder.decode(data)
        if len(t.pending) > PAUSE_CHARS and not t.paused:
            t.paused = True
            self._watch(t)

    def _write_input(self, t: Terminal) -> None:
        try:
            written = os.write(t.fd, bytes(t.inbox[:65536]))
        except (BlockingIOError, InterruptedError):
            written = 0
        except OSError:
            t.inbox.clear()
            written = 0
        del t.inbox[:written]
        self._watch(t)

    def _flush(self, t: Terminal, everything: bool = False) -> None:
        while t.pending:
            text, t.pending = t.pending[:CHUNK_CHARS], t.pending[CHUNK_CHARS:]
            t.seq += 1
            chunk = {"seq": t.seq, "data": text}
            size = len(text.encode("utf-8"))
            t.chunks.append((chunk, size))
            t.bytes += size
            while t.bytes > MAX_OUTPUT and len(t.chunks) > 1:
                t.bytes -= t.chunks.popleft()[1]
            self._broadcast("terminal:data", {"id": t.id, **chunk})
            if not everything:
                break
        t.flushed = time.monotonic()
        if t.paused and len(t.pending) < CHUNK_CHARS:
            t.paused = False
            self._watch(t)

    def _drain(self, t: Terminal, limit: int = 4 * 1024 * 1024) -> None:
        total = 0
        while total < limit:
            try:
                data = os.read(t.fd, 65536)
            except OSError:
                break
            if not data:
                break
            total += len(data)
            t.pending += t.decoder.decode(data)

    def _reap(self, t: Terminal) -> None:
        try:
            pid, status = os.waitpid(t.pid, os.WNOHANG)
        except ChildProcessError:
            pid, status = t.pid, None
        if pid == 0:
            return
        if not t.eof:
            self._drain(t)
        t.pending += t.decoder.decode(b"", final=True)
        self._flush(t, everything=True)
        t.state = "exited"
        t.exit_code = os.waitstatus_to_exitcode(status) if status is not None else -1
        self._watch(t)
        os.close(t.fd)
        t.fd = None
        t.inbox.clear()
        self._broadcast("terminal:exit", {"id": t.id, "exitCode": t.exit_code})

    def _hangup(self, t: Terminal) -> None:
        try:
            os.killpg(t.pid, signal.SIGHUP)
        except OSError:
            try:
                os.kill(t.pid, signal.SIGHUP)
            except OSError:
                pass

    def _spawn(self, shell: str, args: list[str], cwd: str, env: dict[str, str], cols: int, rows: int) -> tuple[int, int]:
        pid, fd = os.forkpty()
        if pid == 0:
            try:
                for name in CHILD_SIGNALS:
                    if hasattr(signal, name):
                        signal.signal(getattr(signal, name), signal.SIG_DFL)
                _set_size(0, cols, rows)
                os.chdir(cwd)
                os.execve(shell, [shell] + args, env)
            finally:
                os._exit(127)
        os.set_inheritable(fd, False)
        os.set_blocking(fd, False)
        return pid, fd

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if len(self.terminals) >= MAX_TABS:
            raise ValueError(f"Limit of {MAX_TABS} terminal tabs reached")
        cwd = _directory(data.get("cwd"))
        shell = _text(data.get("shell"), "executable", 4096)
        if not os.path.isabs(shell):
            raise ValueError("Executable must be absolute")
        args = data.get("args")
        if (not isinstance(args, list) or len(args) > 64
                or any(not isinstance(a, str) or "\0" in a or len(a) > 65536 for a in args)):
            raise ValueError("Invalid arguments")
        for key in ("task", "session"):
            if data.get(key) is not None:
                _text(data[key], key, 128)
        for key in ("title", "kind", "ref"):
            if data.get(key) is not None:
                _text(data[key], key, 256)
        cols, rows = 100, 30
        if data.get("cols") is not None or data.get("rows") is not None:
            cols, rows = _dimensions(data.get("cols"), data.get("rows"))
        if not (os.path.isfile(shell) and os.access(shell, os.X_OK)):
            raise ValueError("Executable is not available")
        env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
        env.update(TERM="xterm-256color", COLORTERM="truecolor")
        if isinstance(data.get("db"), str) and data["db"] and "\0" not in data["db"]:
            env["TASKRIVET_DB"] = data["db"]
        pid, fd = self._spawn(shell, args, cwd, env, cols, rows)
        t = Terminal(pid, fd, cwd, shell, data)
        self.terminals[t.id] = t
        self._watch(t)
        return t.snapshot()

    def dispatch(self, op: Any, data: Any) -> Any:
        data = data if isinstance(data, dict) else {}
        if op == "list":
            return [t.snapshot() for t in self.terminals.values()]
        if op == "create":
            return self.create(data)
        t = self.terminals.get(data.get("id")) if isinstance(data.get("id"), str) else None
        if t is None:
            raise ValueError("Unknown terminal; no command was replayed")
        if op == "write":
            if t.state != "running":
                raise ValueError("Terminal has exited")
            text = data.get("text")
            if not isinstance(text, str) or len(text) > 65536:
                raise ValueError("Invalid input")
            encoded = text.encode("utf-8", "replace")
            if len(t.inbox) + len(encoded) > MAX_INPUT_QUEUE:
                raise ValueError("Terminal input queue is full")
            t.inbox += encoded
            if not t.eof:
                self._write_input(t)
            return True
        if op == "resize":
            cols, rows = _dimensions(data.get("cols"), data.get("rows"))
            if t.state == "running" and t.fd is not None:
                _set_size(t.fd, cols, rows)
            return True
        if op == "stop":
            if t.state == "running":
                self._hangup(t)
            return True
        if op == "remove":
            if t.state == "running":
                raise ValueError("Stop terminal before closing its tab")
            del self.terminals[t.id]
            return True
        raise ValueError("Unsupported session operation")

    # -- clients -----------------------------------------------------------
    def _accept(self) -> None:
        while True:
            try:
                sock, _ = self.server.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            sock.setblocking(False)
            client = Client(sock)
            self.clients.add(client)
            self.selector.register(sock, selectors.EVENT_READ, ("client", client))

    def _client_io(self, client: Client, events: int) -> None:
        if events & selectors.EVENT_WRITE:
            self._pump(client)
        if not events & selectors.EVENT_READ or client.closed:
            return
        try:
            data = client.sock.recv(1 << 20)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self._drop(client)
            return
        client.inbuf += data
        if len(client.inbuf) > MAX_FRAME:
            self._drop(client)
            return
        while not client.closed:
            end = client.inbuf.find(b"\n")
            if end < 0:
                break
            raw = bytes(client.inbuf[:end])
            del client.inbuf[:end + 1]
            self._message(client, raw)

    def _message(self, client: Client, raw: bytes) -> None:
        request: Any = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("Invalid request")
            if not client.authenticated:
                token = request.get("token")
                version = request.get("version")
                if (request.get("op") != "hello" or not isinstance(token, str)
                        or not hmac.compare_digest(token.encode(), self.token.encode())
                        or type(version) is not int or version != VERSION):
                    self._drop(client)
                    return
                client.authenticated = True
                self._send(client, {"id": request.get("id"),
                                    "result": {"version": VERSION, "pid": os.getpid(), "service": "python"}})
                return
            result = self.dispatch(request.get("op"), request.get("data"))
            self._send(client, {"id": request.get("id"), "result": result})
        except Exception as exc:
            if not client.authenticated:
                self._drop(client)
                return
            reply: dict[str, Any] = {"error": str(exc) or type(exc).__name__}
            if isinstance(request, dict) and "id" in request:
                reply["id"] = request["id"]
            self._send(client, reply)

    def _encode(self, message: dict[str, Any]) -> bytes:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "replace") + b"\n"

    def _queue(self, client: Client, line: bytes) -> None:
        if client.closed:
            return
        if len(client.outbuf) + len(line) > MAX_FRAME:
            self._drop(client)
            return
        client.outbuf += line
        self._pump(client)

    def _send(self, client: Client, message: dict[str, Any]) -> None:
        self._queue(client, self._encode(message))

    def _broadcast(self, kind: str, payload: dict[str, Any]) -> None:
        line = self._encode({"event": kind, "payload": payload})
        for client in list(self.clients):
            if client.authenticated:
                self._queue(client, line)

    def _pump(self, client: Client) -> None:
        if client.closed:
            return
        try:
            while client.outbuf:
                sent = client.sock.send(client.outbuf[:1 << 20])
                if sent <= 0:
                    break
                del client.outbuf[:sent]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self._drop(client)
            return
        mask = selectors.EVENT_READ | (selectors.EVENT_WRITE if client.outbuf else 0)
        if mask != client.mask:
            self.selector.modify(client.sock, mask, ("client", client))
            client.mask = mask

    def _drop(self, client: Client) -> None:
        if client.closed:
            return
        client.closed = True
        self.clients.discard(client)
        try:
            self.selector.unregister(client.sock)
        except (KeyError, ValueError):
            pass
        client.sock.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    detach = bool(argv) and argv[0] == "--detach"
    if detach:
        argv = argv[1:]
    if len(argv) != 1:
        print("usage: python -m taskrivet.sessiond [--detach] SESSION_DIR", file=sys.stderr)
        return 2
    ready = -1
    if detach:
        # Fork before creating the selector: a kqueue is not inherited across fork.
        reader, ready = os.pipe()
        if os.fork():
            os.close(ready)
            with os.fdopen(reader, "rb") as pipe:
                started = pipe.read(1) == b"1"
            os._exit(0 if started else 1)
        os.close(reader)
    try:
        directory = private_directory(argv[0])
        service = Service(directory, read_token(directory))
        service.listen()
    except Exception as exc:
        print(f"session service failed to start: {exc}", file=sys.stderr)
        if ready >= 0:
            os.write(ready, b"0")
            os.close(ready)
        return 1
    if ready >= 0:
        os.write(ready, b"1")
        os.close(ready)

    def stop(_signum: int, _frame: Any) -> None:
        service.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    service.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
