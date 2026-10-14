"""Profiles other than the GCC one: the bot must work for any profession and country without code edits."""
import unittest

from jobbot.filters import JobFilter
from jobbot.models import Job
from jobbot.profile import read_yaml
from tests.helpers import PRESETS, profile_from


def job(title, location, desc="", company="Acme", language="en"):
    return Job(source="t", company=company, external_id="1", title=title, url="https://x", location=location,
               description=desc, language=language)


class BackendGermany(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = JobFilter(profile_from({
            "region": "dach",
            "tracks": [{"preset": "backend"}],
            "languages": ["english", "german"],
            "salary": {"min": 55000, "currency": "EUR", "period": "year"},
            "locations": {"home": "Berlin", "home_country": "Germany"},
            "blocked": {"title_keywords": ["salesforce"], "companies": ["Bad Corp"]},
        }))

    def check(self, *a, **kw):
        return self.f.evaluate(job(*a, **kw))

    def test_berlin_backend_kept(self):
        v = self.check("Backend Engineer (Python)", "Berlin, Germany",
                       "Python, Django and PostgreSQL. 3+ years of experience.")
        self.assertTrue(v.keep, v.reason)
        self.assertEqual(v.city, "Berlin")
        self.assertEqual(v.track, "backend")
        self.assertNotIn("no nationality limits", v.positives)  # no nationals rules in this profile

    def test_language_rules_follow_profile(self):
        self.assertTrue(self.check("Python Developer", "Munich", "Fluent German is required.").keep)
        self.assertIn("French", self.check("Python Developer", "Munich", "Fluent French is required.").reason)

    def test_locations(self):
        self.assertIn("outside DACH", self.check("Backend Engineer", "Dubai, United Arab Emirates").reason)
        self.assertTrue(self.check("Backend Engineer", "Remote - Europe").keep)
        self.assertIn("remote limited", self.check("Backend Engineer", "Remote, United States").reason)

    def test_salary_in_euro_per_year(self):
        self.assertIn("EUR/year", self.check("Backend Engineer", "Berlin", "Salary: €40,000 per year.").reason)
        v = self.check("Backend Engineer", "Berlin", "Salary: €65,000 per year.")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("~65k EUR/yr", v.positives)

    def test_other_roles_dropped(self):
        self.assertIn("not a backend role", self.check("Flutter Developer", "Berlin").reason)
        self.assertIn("not a backend role", self.check("Frontend Engineer", "Berlin").reason)

    def test_blocked(self):
        self.assertIn("blocked keyword", self.check("Salesforce Backend Developer", "Berlin").reason)
        self.assertIn("blocked company", self.check("Backend Engineer", "Berlin", company="Bad Corp").reason)

    def test_german_titles(self):
        for title in ("Python Entwickler (m/w/d)", "Backend-Entwicklerin (w/m/d)", "Java-Entwickler",
                      "Softwareentwickler Backend"):
            v = self.check(title, "Berlin", "Python und PostgreSQL.")
            self.assertTrue(v.keep, f"{title}: {v.reason}")
        self.assertIn("graduate", self.check("Werkstudent Backend-Entwickler (m/w/d)", "Berlin").reason)

    def test_german_and_bare_years(self):
        self.assertIn("7+ years", self.check("Backend Engineer", "Berlin", "Mindestens 7 Jahre Berufserfahrung.").reason)
        self.assertIn("7+ years", self.check("Backend Engineer", "Berlin", "Requirements:\n7+ years.").reason)
        self.assertTrue(self.check("Backend Engineer", "Berlin", "We have been around for 20+ years.").keep)
        self.assertTrue(self.check("Backend Engineer", "Berlin", "3+ Jahre Erfahrung mit Python.").keep)

    def test_collective_agreement_minimum_is_not_the_pay(self):
        v = self.check("Backend Engineer", "Vienna, Austria",
                       "The salary is from EUR 52,000 per year. Overpayment depending on experience.")
        self.assertTrue(v.keep, v.reason)
        self.assertTrue(any("a minimum" in w for w in v.warnings))
        self.assertIn("salary", self.check("Backend Engineer", "Vienna", "Salary: EUR 40,000 per year.").reason)


class DataAnalystUS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = JobFilter(profile_from({
            "region": "us",
            "tracks": [{"preset": "data", "levels": ["junior", "mid"]}],
            "salary": {"min": 70000, "currency": "USD", "period": "year"},
            "locations": {"home_country": "the US"},
        }))

    def check(self, *a, **kw):
        return self.f.evaluate(job(*a, **kw))

    def test_analyst_allowed_for_data_track(self):
        v = self.check("Data Analyst", "New York, NY", "SQL and Tableau. 2+ years of experience.")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("2+ yrs", v.positives)

    def test_other_analysts_still_excluded(self):
        self.assertFalse(self.check("Sales Analyst", "New York, NY").keep)

    def test_us_matching_is_case_sensitive(self):
        self.assertTrue(self.check("Data Analyst", "Remote - US").keep)
        v = self.check("Data Analyst", "Remote", "Wherever you are, come and join us.")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("Remote region not stated", v.warnings)  # "us" is not the US

    def test_outside_and_seniority(self):
        self.assertIn("outside the US", self.check("Data Analyst", "London, United Kingdom").reason)
        self.assertIn("senior title", self.check("Senior Data Analyst", "Austin, TX").reason)

    def test_salary_range(self):
        v = self.check("Data Analyst", "Chicago, IL", "Pay: $85,000 - $100,000 a year.")
        self.assertIn("~100k USD/yr", v.positives)


class Policies(unittest.TestCase):
    def base(self, **loc):
        return JobFilter(profile_from({"region": "uk", "tracks": [{"preset": "frontend"}],
                                       "locations": loc, "salary": {"currency": "GBP"}}))

    def test_remote_only(self):
        f = self.base(work_modes=["remote"])
        self.assertIn("on-site not wanted", f.evaluate(job("Frontend Developer", "London")).reason)
        self.assertTrue(f.evaluate(job("Frontend Developer", "Remote, UK")).keep)

    def test_no_remote(self):
        f = self.base(remote="none")
        self.assertIn("remote outside", f.evaluate(job("Frontend Developer", "Remote, Worldwide")).reason)

    def test_remote_anywhere(self):
        f = self.base(remote="anywhere")
        self.assertTrue(f.evaluate(job("Frontend Developer", "Remote", "You must be based in the US.")).keep)


class Presets(unittest.TestCase):
    def test_every_track_preset_compiles_and_matches_its_own_title(self):
        titles = {"mobile": "Flutter Developer", "ios": "iOS Engineer", "backend": "Backend Engineer",
                  "frontend": "Frontend Developer", "fullstack": "Full Stack Engineer", "data": "Data Engineer",
                  "ai-ml": "Machine Learning Engineer", "devops": "DevOps Engineer", "qa": "QA Engineer",
                  "product-design": "Product Designer"}
        presets = sorted(p.stem for p in (PRESETS / "tracks").glob("*.yml"))
        self.assertEqual(presets, sorted(titles))
        for name in presets:
            f = JobFilter(profile_from({"region": "uk", "tracks": [{"preset": name}], "salary": {"currency": "GBP"}}))
            v = f.evaluate(job(titles[name], "London, United Kingdom"))
            self.assertTrue(v.keep, f"{name}: {v.reason}")

    def test_override_preset_fields(self):
        p = profile_from({"tracks": [{"preset": "backend", "levels": ["junior"], "label": "server"}]})
        self.assertEqual(p.tracks[0].levels, ["junior"])
        self.assertEqual(p.not_relevant, "not a server role")

    def test_every_region_pack_compiles(self):
        for path in (PRESETS / "regions").glob("*.yml"):
            p = profile_from({"region": path.stem, "tracks": [{"preset": "backend"}]})
            self.assertTrue(p.targets, path.stem)
            self.assertIsInstance(read_yaml(path), dict)

    def test_unknown_preset_lists_the_available_ones(self):
        with self.assertRaises(ValueError) as ctx:
            profile_from({"tracks": [{"preset": "astronaut"}]})
        self.assertIn("backend", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
