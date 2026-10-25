"""The standard-library session service and its client."""
import hashlib
import io
import os
from pathlib import Path
import signal
import time
import unittest
from unittest.mock import patch

from synthetic import cleanup, short_dir, stop_service, wait_for_exit
from taskrivet.session_client import (
    RequestRefused, ServiceNotRunning, SessionClient, SessionError, attach, find_terminal, session_dir, summarize)


class SessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.base = short_dir()
        self.dir = self.base / "s"
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        stop_service(self.dir)
        cleanup(self.base)

    def client(self):
        client = SessionClient(self.dir)
        self.clients.append(client)
        return client

    def shell(self, client, script, **extra):
        return client.request("create", {"cwd": "/tmp", "shell": "/bin/sh", "args": ["-c", script], **extra})

    def test_not_running_creates_nothing(self):
        with self.assertRaises(ServiceNotRunning):
            SessionClient(self.dir).connect(start=False)
        self.assertFalse(self.dir.exists())

    def test_starts_on_demand_and_is_shared(self):
        hello = self.client().connect()
        self.assertEqual(hello["service"], "python")
        self.assertEqual(self.dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.dir / "token").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.dir / "sessions.sock").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client().connect(start=False)["pid"], hello["pid"])

    def test_terminal_lifecycle_and_scrollback(self):
        client = self.client()
        client.connect()
        t = self.shell(client, "printf 'hello\\n'; exit 3", title="synthetic", kind="shell", ref="SYN-1")
        record, output = wait_for_exit(self.dir, t["id"])
        self.assertEqual(record["exitCode"], 3)
        self.assertIn("hello", output)
        view = summarize(record)
        self.assertEqual((view["title"], view["ref"], view["exit_code"], view["last_line"]), ("synthetic", "SYN-1", 3, "hello"))
        buffer = io.BytesIO()
        result = attach(client, t["id"][:8], interactive=False, out=buffer)
        self.assertEqual((result["state"], result["exit_code"]), ("exited", 3))
        self.assertIn(b"hello", buffer.getvalue())
        client.request("remove", {"id": t["id"]})
        self.assertEqual(client.request("list"), [])
        with self.assertRaises(RequestRefused):
            client.request("write", {"id": t["id"], "text": "x"})

    def test_input_and_stop(self):
        client = self.client()
        client.connect()
        cat = client.request("create", {"cwd": "/tmp", "shell": "/bin/cat", "args": []})
        client.request("write", {"id": cat["id"], "text": "ping\n"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = find_terminal(client.request("list"), cat["id"])
            if "ping" in "".join(c["data"] for c in current["chunks"]):
                break
            time.sleep(0.05)
        else:
            self.fail("cat did not echo input")
        client.request("stop", {"id": cat["id"]})
        record, _ = wait_for_exit(self.dir, cat["id"])
        self.assertEqual(record["state"], "exited")
        with self.assertRaises(RequestRefused):
            client.request("create", {"cwd": "/tmp", "shell": "sh", "args": []})

    def test_follow_streams_until_exit(self):
        client = self.client()
        client.connect()
        t = self.shell(client, "sleep 0.3; printf 'late\\n'; exit 4")
        buffer = io.BytesIO()
        result = attach(client, t["id"], interactive=False, out=buffer)
        self.assertEqual((result["state"], result["exit_code"], result["detached"]), ("exited", 4, False))
        self.assertIn(b"late", buffer.getvalue())

    def test_no_follow_leaves_a_running_terminal_alone(self):
        client = self.client()
        client.connect()
        t = self.shell(client, "sleep 5")
        result = attach(client, t["id"], follow=False, out=io.BytesIO())
        self.assertTrue(result["detached"])
        self.assertEqual(find_terminal(client.request("list"), t["id"])["state"], "running")
        client.request("stop", {"id": t["id"]})

    def test_stale_socket_is_replaced(self):
        first = self.client().connect()
        os.kill(first["pid"], signal.SIGKILL)
        time.sleep(0.2)
        self.assertTrue((self.dir / "sessions.sock").exists())
        second = self.client().connect()
        self.assertNotEqual(first["pid"], second["pid"])

    def test_mismatched_token_is_refused(self):
        pid = self.client().connect()["pid"]
        (self.dir / "token").write_text("0" * 64)
        try:
            with self.assertRaisesRegex(SessionError, "refused the handshake"):
                SessionClient(self.dir).connect()
        finally:
            os.kill(pid, signal.SIGTERM)

    def test_service_exits_when_its_socket_is_removed(self):
        pid = self.client().connect()["pid"]
        (self.dir / "sessions.sock").unlink()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.kill(pid, signal.SIGTERM)
        self.fail("orphaned service kept running")

    def test_unsafe_directory_is_refused(self):
        self.dir.mkdir(mode=0o755)
        self.dir.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "0700"):
            SessionClient(self.dir).connect()

    def test_run_variables_do_not_leak_into_the_service(self):
        with patch.dict(os.environ, {"TASKRIVET_SESSION": "leaked", "TASKRIVET_CONTEXT": "/leaked"}):
            client = self.client()
            client.connect()
        t = self.shell(client, 'printf "[%s|%s]" "$TASKRIVET_SESSION" "$TASKRIVET_CONTEXT"')
        _, output = wait_for_exit(self.dir, t["id"])
        self.assertIn("[|]", output)

    def test_session_dir_matches_the_desktop_derivation(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASKRIVET_SESSION_DIR", None)
            digest = hashlib.sha256(b"/tmp/example/ledger.sqlite").hexdigest()[:12]
            self.assertEqual(session_dir("/tmp/example/../example/ledger.sqlite"),
                             Path.home() / ".taskrivet" / f"sessions-{digest}")
        with patch.dict(os.environ, {"TASKRIVET_SESSION_DIR": str(self.dir)}):
            self.assertEqual(session_dir("/anything"), self.dir)


if __name__ == "__main__":
    unittest.main()
