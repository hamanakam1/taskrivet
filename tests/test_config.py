"""Private local config and launcher profiles."""
import os
from pathlib import Path
import tempfile
import unittest

from taskrivet import config, launchers
from taskrivet.loop import launch_argv


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_is_private(self):
        config.set_value("ticket_service.origin", "http://127.0.0.1:8123", self.path)
        config.set_value("ticket_service.timeout", "12", self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.get_value("ticket_service.timeout", self.path), 12)
        self.assertEqual(config.ticket_origin(config.load(self.path)), "http://127.0.0.1:8123")
        self.assertEqual(config.ticket_timeout(config.load(self.path)), 12)
        config.unset_value("ticket_service.timeout", self.path)
        config.unset_value("ticket_service.origin", self.path)
        self.assertEqual(config.load(self.path), {})
        with self.assertRaisesRegex(ValueError, "is not set"):
            config.get_value("ticket_service.origin", self.path)

    def test_rejects_unsafe_files(self):
        self.path.write_text("{}")
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "0600"):
            config.load(self.path)
        self.path.chmod(0o600)
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            config.load(link)
        self.path.write_text("{not json")
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            config.load(self.path)

    def test_rejects_invalid_values_without_writing(self):
        bad = [
            ("ticket_service.origin", "https://example.com"),
            ("ticket_service.origin", "http://10.0.0.5:80"),
            ("ticket_service.ticket_url", "http://example.com/{key}"),
            ("ticket_service.ticket_url", "http://127.0.0.1.example.com/{key}"),
            ("ticket_service.ticket_url", "http://localhost:{key}/"),
            ("ticket_service.ticket_url", "http://127.0.0.1:8123/no-placeholder"),
            ("ticket_service.timeout", "0"),
            ("ticket_adapter.argv", '["relative/script"]'),
            ("launchers.codex.argv", '"not-a-list"'),
            ("launchers.codex.disabled", '""'),
            ("nonsense", "1"),
            ("workdir", "relative/path"),
        ]
        for key, value in bad:
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.set_value(key, value, self.path)
        self.assertFalse(self.path.exists())

    def test_missing_file_means_defaults_and_a_clear_error(self):
        self.assertEqual(config.load(self.path), {})
        with self.assertRaisesRegex(ValueError, "No ticket service configured"):
            config.ticket_origin({})
        self.assertEqual(config.ticket_timeout({}), 30)
        self.assertEqual(config.ticket_origin({}, "http://localhost:9000/"), "http://localhost:9000")
        self.assertIsNone(config.ticket_link({}, "SYN-1"))

    def test_ticket_link_quotes_the_key(self):
        config.set_value("ticket_service.ticket_url", "http://127.0.0.1:8123/#/ticket/{key}", self.path)
        cfg = config.load(self.path)
        self.assertEqual(config.ticket_link(cfg, "SYN-1"), "http://127.0.0.1:8123/#/ticket/SYN-1")
        self.assertEqual(config.ticket_link(cfg, "a/b c"), "http://127.0.0.1:8123/#/ticket/a%2Fb%20c")

    def test_environment_overrides_the_config_path(self):
        old = os.environ.get("TASKRIVET_CONFIG")
        os.environ["TASKRIVET_CONFIG"] = str(self.path)
        try:
            self.assertEqual(config.config_path(), self.path)
        finally:
            if old is None:
                del os.environ["TASKRIVET_CONFIG"]
            else:
                os.environ["TASKRIVET_CONFIG"] = old


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        for name in ("codex", "gemini"):
            (self.bin / name).write_text("#!/bin/sh\n")
            (self.bin / name).chmod(0o755)
        self.paths = [str(self.bin)]

    def tearDown(self):
        self.temp.cleanup()

    def test_builtin_profiles_and_render(self):
        r = launchers.resolve("codex", {}, self.paths)
        self.assertEqual(r["argv"], [str(self.bin / "codex"), "{prompt}"])
        self.assertTrue(r["prompt"])
        self.assertEqual(launchers.render(r["argv"], "do it", "/c.md"), [str(self.bin / "codex"), "do it"])
        self.assertEqual(launchers.resolve("gemini", {}, self.paths)["argv"][1:], ["-i", "{prompt}"])

    def test_missing_or_unsafe_tools_are_refused(self):
        with self.assertRaisesRegex(ValueError, "not installed"):
            launchers.resolve("claude", {}, self.paths)
        with self.assertRaises(ValueError):
            launchers.resolve("../codex", {}, self.paths)

    def test_config_launchers_override_and_disable(self):
        cfg = {"launchers": {
            "codex": {"argv": [str(self.bin / "gemini"), "--ctx", "{context}", "{prompt}"]},
            "claude": {"disabled": "paid lane needs approval"},
        }}
        r = launchers.resolve("codex", cfg, self.paths)
        self.assertEqual(r["source"], "local config")
        self.assertEqual(launchers.render(r["argv"], "p", "/c.md"), [str(self.bin / "gemini"), "--ctx", "/c.md", "p"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            launchers.resolve("claude", cfg, self.paths)
        rows = {x["tool"]: x for x in launchers.catalog(cfg, self.paths)}
        self.assertEqual(rows["claude"]["status"], "disabled")
        self.assertEqual(rows["codex"]["status"], "ready")
        self.assertEqual(rows["gemini"]["status"], "ready")
        self.assertEqual(rows["opencode"]["status"], "not installed")

    def test_no_prompt_drops_prompt_arguments(self):
        builtin = launchers.resolve("gemini", {}, self.paths)
        self.assertEqual(launch_argv(builtin, None, Path("/c.md")), [str(self.bin / "gemini")])
        custom = {"argv": ["/x/agent", "--ctx", "{context}", "--prompt={prompt}"], "source": "local config"}
        self.assertEqual(launch_argv(custom, None, Path("/c.md")), ["/x/agent", "--ctx", "/c.md"])
        self.assertEqual(launch_argv(custom, "go", Path("/c.md")), ["/x/agent", "--ctx", "/c.md", "--prompt=go"])


if __name__ == "__main__":
    unittest.main()
