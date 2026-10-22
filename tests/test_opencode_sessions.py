"""Local OpenCode session metadata. Fixtures are synthetic."""
import json
import os
import tempfile
import unittest
import unittest.mock
from types import SimpleNamespace

from taskrivet import opencode_sessions


def synthetic_folder(name):
    """A real empty folder so path checks behave as they do in production."""
    path = tempfile.mkdtemp(prefix=f"tr-opencode-{name}-")
    return path


class FakeRunner:
    """Answers OpenCode CLI calls from synthetic fixtures only."""

    def __init__(self, projects=None, sessions=None, cli_sessions=None, api_error=False, version="opencode v0.0.0-test"):
        self.projects = projects if projects is not None else []
        self.sessions = sessions if sessions is not None else {}
        self.cli_sessions = cli_sessions
        self.api_error = api_error
        self.version = version
        self.calls = []

    def __call__(self, args, cwd=None):
        command = list(args)
        self.calls.append((command, cwd))
        tail = command[1:]
        if tail[:2] == ["api", "project.list"]:
            return SimpleNamespace(stdout=json.dumps(self.projects), stderr="", returncode=0)
        if tail[:2] == ["api", "session.list"]:
            if self.api_error:
                return SimpleNamespace(stdout="", stderr="unavailable", returncode=1)
            directory = next((a.split("=", 1)[1] for a in tail if a.startswith("directory=")), "")
            rows = self.sessions.get(directory, [])
            return SimpleNamespace(stdout=json.dumps({"data": rows}), stderr="", returncode=0)
        if tail[:1] == ["session"]:
            rows = self.cli_sessions if self.cli_sessions is not None else []
            return SimpleNamespace(stdout=json.dumps(rows), stderr="", returncode=0)
        if tail[:1] == ["--version"]:
            return SimpleNamespace(stdout=self.version, stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {command}")


def session_record(identifier, title="Synthetic session", directory="/tmp/project", updated=1000):
    return {
        "id": identifier,
        "title": title,
        "location": {"directory": directory},
        "projectID": "project-1",
        "agent": "build",
        "model": {"id": "model-x", "providerID": "opencode"},
        "time": {"created": 500, "updated": updated},
    }


class NormalizeTests(unittest.TestCase):
    def test_only_metadata_is_kept(self):
        item = opencode_sessions.normalize(
            {"id": "ses_1", "title": "Fix  the   search state", "location": {"directory": "/tmp/p"},
             "time": {"created": 5, "updated": 9}, "model": {"id": "m1"},
             "messages": [{"text": "private transcript"}], "cost": 1.5},
            None,
        )
        self.assertEqual(item["id"], "ses_1")
        self.assertEqual(item["title"], "Fix the search state")
        self.assertEqual(item["directory"], "/tmp/p")
        self.assertEqual(item["updated"], 9)
        self.assertNotIn("messages", item)
        self.assertNotIn("cost", item)

    def test_records_without_identifier_are_dropped(self):
        self.assertIsNone(opencode_sessions.normalize({"title": "no id"}, None))
        self.assertIsNone(opencode_sessions.normalize("not a record", None))

    def test_titles_are_bounded(self):
        item = opencode_sessions.normalize({"id": "ses_2", "title": "x" * 500}, None)
        self.assertEqual(len(item["title"]), 200)

    def test_missing_folder_falls_back_to_the_queried_project(self):
        item = opencode_sessions.normalize({"id": "ses_3"}, "/tmp/fallback")
        self.assertEqual(item["directory"], "/tmp/fallback")
        self.assertFalse(item["directory_available"])

    def test_existing_folder_is_marked_available(self):
        folder = synthetic_folder("available")
        try:
            item = opencode_sessions.normalize({"id": "ses_4", "location": {"directory": folder}}, None)
            self.assertTrue(item["directory_available"])
        finally:
            os.rmdir(folder)


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.project = synthetic_folder("project")
        self.other = synthetic_folder("other")
        self.addCleanup(lambda: [os.rmdir(p) for p in (self.project, self.other) if os.path.isdir(p)])

    def test_sessions_are_sorted_deduplicated_and_bounded(self):
        runner = FakeRunner(
            projects=[{"canonical": self.project, "time": {"active": 20}}],
            sessions={
                self.project: [
                    session_record("ses_old", updated=100),
                    session_record("ses_new", updated=900),
                    session_record("ses_old", updated=100),
                    session_record("ses_mid", updated=500),
                ]
            },
        )
        result = opencode_sessions.discover(limit=2, runner=runner, exe="/bin/opencode")
        self.assertTrue(result["available"])
        self.assertEqual([s["id"] for s in result["sessions"]], ["ses_new", "ses_mid"])
        self.assertTrue(result["truncated"])

    def test_no_opencode_binary_is_reported_not_guessed(self):
        with unittest.mock.patch.object(opencode_sessions, "executable", return_value=None):
            result = opencode_sessions.discover(runner=lambda args, cwd=None: None)
        self.assertFalse(result["available"])
        self.assertEqual(result["sessions"], [])
        self.assertIn("not found", result["reason"])

    def test_project_scope_reads_only_that_folder(self):
        runner = FakeRunner(
            projects=[{"canonical": self.other}],
            sessions={self.project: [session_record("ses_scoped", directory=self.project)]},
        )
        result = opencode_sessions.discover(project=self.project, runner=runner, exe="/bin/opencode")
        self.assertEqual([s["id"] for s in result["sessions"]], ["ses_scoped"])
        for command, _ in runner.calls:
            self.assertNotIn(self.other, " ".join(command))

    def test_cli_fallback_when_the_api_is_unavailable(self):
        runner = FakeRunner(
            projects=[{"canonical": self.project}],
            api_error=True,
            cli_sessions=[{"id": "ses_cli", "title": "From the CLI", "directory": self.project, "updated": 42}],
        )
        result = opencode_sessions.discover(runner=runner, exe="/bin/opencode")
        self.assertEqual([s["id"] for s in result["sessions"]], ["ses_cli"])
        self.assertEqual(result["sessions"][0]["updated"], 42)

    def test_metadata_only_commands_are_used(self):
        runner = FakeRunner(projects=[{"canonical": self.project}], sessions={self.project: [session_record("ses_a")]})
        opencode_sessions.discover(runner=runner, exe="/bin/opencode")
        for command, _ in runner.calls:
            joined = " ".join(command)
            self.assertNotIn("message", joined)
            self.assertNotIn("export", joined)
            self.assertNotIn("delete", joined)

    def test_scope_and_limitations_are_declared(self):
        runner = FakeRunner(projects=[{"canonical": self.project}], sessions={self.project: [session_record("ses_a")]})
        result = opencode_sessions.discover(runner=runner, exe="/bin/opencode")
        self.assertIn("No transcripts", result["scope"])
        self.assertTrue(result["limitations"])

    def test_unreadable_project_is_recorded_not_hidden(self):
        class Broken(FakeRunner):
            def __call__(self, args, cwd=None):
                command = list(args)
                if command[1:3] == ["api", "session.list"] or command[1:2] == ["session"]:
                    raise OSError("server refused the connection")
                return super().__call__(args, cwd)

        runner = Broken(projects=[{"canonical": self.project}])
        result = opencode_sessions.discover(runner=runner, exe="/bin/opencode")
        self.assertTrue(result["problems"])
        self.assertEqual(result["sessions"], [])


if __name__ == "__main__":
    unittest.main()
