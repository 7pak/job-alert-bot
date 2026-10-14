"""Config loading, example fallback, validation messages and `jobbot init`."""
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from jobbot import __main__ as cli
from jobbot import setup
from jobbot.config import ConfigError, load_config
from jobbot.filters import JobFilter
from tests.helpers import ROOT

EXAMPLES = ("config.example.yml", "profile.example.yml", "companies.example.yml")


class Home(unittest.TestCase):
    """Each test gets an empty JOBBOT_HOME with the example files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for name in EXAMPLES:
            shutil.copy(ROOT / name, self.home / name)
        self._old = os.environ.get("JOBBOT_HOME")
        os.environ["JOBBOT_HOME"] = str(self.home)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("JOBBOT_HOME", None)
        else:
            os.environ["JOBBOT_HOME"] = self._old
        self.tmp.cleanup()

    def write(self, name, text):
        (self.home / name).write_text(text, encoding="utf-8")


class FreshClone(Home):
    def test_examples_work_without_any_setup(self):
        cfg = load_config()
        self.assertTrue(any("config.example.yml" in n for n in cfg["notices"]))
        self.assertTrue(any("profile.example.yml" in n for n in cfg["notices"]))
        self.assertEqual(cfg["report"].errors, [])
        JobFilter(cfg["profile"], cfg["money"])  # builds
        self.assertTrue(cfg["companies"]["greenhouse"])
        self.assertNotIn("linkedin", [n for n, c in cfg["sources"].items() if c.get("enabled", True)])
        self.assertFalse(cfg["ai"]["enabled"])
        self.assertFalse(cfg["tailoring"]["enabled"])

    def init(self, *args, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            code = setup.init(*args, **kw)
        return code, out.getvalue()

    def read(self, name):
        return yaml.safe_load((self.home / name).read_text(encoding="utf-8"))

    def test_init_without_answers_uses_the_example_and_says_so(self):
        self.write("config.yml", "poll_seconds: 300\n")
        code, out = self.init(yes=True)
        self.assertEqual(code, 0)
        self.assertIn("Not asking questions", out)
        self.assertEqual((self.home / "config.yml").read_text(encoding="utf-8"), "poll_seconds: 300\n")
        self.assertIn("--force", out)
        prof = self.read("profile.yml")
        self.assertEqual((prof["region"], prof["timezone"]), ("dach", "Europe/Berlin"))
        cfg = load_config()
        self.assertEqual(cfg["notices"], [])
        self.assertEqual(cfg["report"].errors, [])

    def test_init_with_flags_sets_profile_and_search_sources(self):
        code, _ = self.init(["data"], "us", None)
        self.assertEqual(code, 0)
        prof = self.read("profile.yml")
        self.assertEqual((prof["region"], prof["name"]), ("us", "data in US"))
        self.assertEqual(prof["timezone"], "America/New_York")  # suggested by the region pack
        self.assertEqual(prof["tracks"], [{"preset": "data"}])
        self.assertEqual(prof["languages"], [{"name": "english", "level": "fluent"}])
        self.assertEqual((prof["salary"]["currency"], prof["salary"]["min"]), ("USD", 0))
        src = self.read("config.yml")["sources"]
        self.assertEqual(src["workable_search"]["locations"], ["United States"])
        self.assertIn("data engineer", src["workable_search"]["queries"])
        self.assertEqual(src["himalayas"]["country"], "US")
        self.assertEqual(src["careerjet"]["locales"], ["en_US"])
        self.assertEqual(src["linkedin"]["queries"][0], {"keywords": "data engineer", "location": "United States"})
        self.assertFalse(src["linkedin"]["enabled"])
        cfg = load_config()
        self.assertEqual(cfg["report"].errors, [])
        self.assertEqual(cfg["profile"].tracks[0].name, "data")

    def test_init_track_only_keeps_example_region_and_timezone(self):
        self.init(["frontend"], None, None)
        prof = self.read("profile.yml")
        self.assertEqual((prof["region"], prof["timezone"]), ("dach", "Europe/Berlin"))

    def test_force_replaces_and_unknown_names_fail(self):
        self.init(["backend"], "uk", "Europe/London")
        self.assertEqual(self.read("profile.yml")["region"], "uk")
        self.init(["backend"], "us", None)
        self.assertEqual(self.read("profile.yml")["region"], "uk")  # kept without --force
        self.init(["backend"], "us", None, force=True)
        self.assertEqual(self.read("profile.yml")["region"], "us")
        self.assertEqual(self.init(["astronaut"], None, None)[0], 1)
        self.assertEqual(self.init(None, "mars", None)[0], 1)
        self.assertEqual(self.init(None, None, "Mars/Base")[0], 1)


class Validation(Home):
    def test_unknown_key_is_a_warning_with_line_and_hint(self):
        self.write("config.yml", "max_job_age_hours: 24\npoll_secnds: 300\n")
        rep = load_config()["report"]
        self.assertTrue(any("config.yml:2" in w and "Did you mean 'poll_seconds'" in w for w in rep.warnings),
                        rep.warnings)

    def test_wrong_type_is_an_error_with_line(self):
        self.write("config.yml", "max_alerts_per_cycle: lots\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("config.yml:1: max_alerts_per_cycle: expected a whole number", str(ctx.exception))

    def test_list_written_as_text(self):
        self.write("profile.yml", "tracks:\n  - preset: backend\nlanguages: english\n")
        rep = load_config(strict=False)["report"]
        self.assertTrue(any("profile.yml:3: languages" in e for e in rep.errors), rep.errors)

    def test_bad_yaml_points_to_the_line(self):
        self.write("config.yml", "sources:\n  greenhouse: {interval_seconds: 180\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("not valid YAML", str(ctx.exception))

    def test_interval_floor(self):
        self.write("config.yml", "sources:\n  linkedin:\n    interval_seconds: 30\n    queries: [{keywords: x, location: y}]\n")
        cfg = load_config()
        self.assertEqual(cfg["sources"]["linkedin"]["interval_seconds"], 600)
        self.assertTrue(any("safe minimum" in w for w in cfg["report"].warnings))

    def test_profile_value_checks(self):
        self.write("profile.yml", "timezone: Mars/Base\ntracks:\n  - {preset: backend, levels: [guru]}\n"
                                  "salary: {currency: XYZ}\nlocations: {remote: sometimes}\n")
        errors = " ".join(load_config(strict=False)["report"].errors)
        for fragment in ("timezone 'Mars/Base'", "unknown level ['guru']", "XYZ is not in currency_rates",
                         "locations.remote must be"):
            self.assertIn(fragment, errors)

    def test_folder_instead_of_file(self):
        (self.home / "profile.yml").mkdir()
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("profile.yml is a folder", str(ctx.exception))

    def test_unknown_preset(self):
        self.write("profile.yml", "tracks: [{preset: astronaut}]\n")
        errors = " ".join(load_config(strict=False)["report"].errors)
        self.assertIn("unknown track preset 'astronaut'", errors)

    def test_empty_queries_is_an_error(self):
        self.write("config.yml", "sources:\n  himalayas: {country: DE}\n")
        errors = " ".join(load_config(strict=False)["report"].errors)
        self.assertIn("sources.himalayas.queries is empty", errors)

    def test_check_config_command(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.cmd_check_config(None), 0)
        self.assertIn("Config OK", out.getvalue())
        self.assertNotIn("TELEGRAM_BOT_TOKEN set", out.getvalue())
        self.write("config.yml", "notifier: pigeon\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_check_config(None), 1)


if __name__ == "__main__":
    unittest.main()
