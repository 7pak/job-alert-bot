import unittest

from jobbot.filters import JobFilter
from jobbot.models import Job
from jobbot.money import Money
from tests.helpers import AED_RATES, gcc_profile

F = JobFilter(gcc_profile(), Money(AED_RATES))


def job(title="Flutter Engineer", location="Dubai, United Arab Emirates", desc="", language="en"):
    return Job(source="t", company="Acme", external_id="1", title=title, url="https://x", location=location,
               description=desc, language=language)


def check(**kw):
    return F.evaluate(job(**kw))


class Keeps(unittest.TestCase):
    def test_flutter_dubai(self):
        v = check(desc="We use Flutter and BLoC. 2-4 years of experience building mobile apps.")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("Flutter", v.positives)
        self.assertIn("2-4 yrs", v.positives)
        self.assertEqual(v.city, "Dubai")
        self.assertGreaterEqual(v.score, 4.0)

    def test_android_riyadh(self):
        self.assertTrue(check(title="Android Developer (Kotlin)", location="Riyadh, Saudi Arabia").keep)

    def test_ai_engineer_remote_mena(self):
        v = check(title="AI Engineer", location="Remote - MENA", desc="Build LLM agents in Python.")
        self.assertTrue(v.keep, v.reason)

    def test_plain_remote_warns(self):
        v = check(location="Remote")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("Remote region not stated", v.warnings)

    def test_german_nice_to_have_is_warning(self):
        v = check(desc="German is a plus.")
        self.assertTrue(v.keep, v.reason)
        self.assertTrue(any("German" in w for w in v.warnings))

    def test_swift_plus_warning(self):
        v = check(desc="Experience with Swift is a nice to have.")
        self.assertIn("Mentions Swift as a plus", v.warnings)

    def test_saudi_national_bank_ok(self):
        self.assertTrue(check(desc="Clients include Saudi National Bank.").keep)

    def test_join_us_is_not_us_restriction(self):
        self.assertTrue(check(location="Remote", desc="Wherever you are based, come and join us.").keep)

    def test_generic_title_with_flutter_desc(self):
        self.assertTrue(check(title="Software Engineer", desc="Flutter app. Flutter and Firebase.").keep)

    def test_salary_ok(self):
        v = check(desc="Salary: AED 12,000 - 15,000 per month.")
        self.assertTrue(v.keep, v.reason)
        self.assertIn("~15k AED/mo", v.positives)


class Drops(unittest.TestCase):
    def assertDrop(self, v, fragment):
        self.assertFalse(v.keep, "expected drop")
        self.assertIn(fragment, v.reason)

    def test_not_relevant(self):
        self.assertDrop(check(title="Account Manager I"), "not a mobile, AI or software")
        self.assertDrop(check(title="Senior Product Designer"), "not a mobile, AI or software")
        self.assertDrop(check(title="Software Engineer II - Backend"), "not junior")
        self.assertDrop(check(title="Embedded Software Engineer"), "not a mobile, AI or software")

    def test_nationals(self):
        self.assertDrop(check(desc="This role is open to UAE Nationals only."), "nationals")
        self.assertDrop(check(desc="Part of our Emiratisation program."), "nationals")
        self.assertDrop(check(desc="Saudi nationals only."), "nationals")

    def test_language(self):
        self.assertDrop(check(desc="Fluent German is required."), "German")
        self.assertDrop(check(desc="Business-level Portuguese (C1)."), "Portuguese")
        self.assertDrop(check(language="de"), "posting language")

    def test_location(self):
        self.assertDrop(check(location="London, United Kingdom"), "outside GCC")
        self.assertDrop(check(location="Berlin", desc="Hybrid, 3 days in office."), "hybrid outside GCC")
        self.assertDrop(check(location="Remote - Europe"), "remote limited")
        self.assertDrop(check(location="Remote", desc="You must be based in the US."), "remote restricted")
        self.assertDrop(check(location="Remote", desc="Remote (EU only)."), "remote restricted")

    def test_seniority(self):
        for t in ("Staff Flutter Engineer", "Lead Mobile Engineer", "Head of Flutter", "Principal Android Engineer"):
            self.assertDrop(check(title=t), "too senior")
        self.assertFalse(check(title="Head of Mobile").keep)
        self.assertDrop(check(desc="You have 5+ years of experience in mobile."), "5+ years")
        self.assertDrop(check(desc="Minimum of six years in software."), "6+ years")

    def test_stack(self):
        self.assertDrop(check(title="React Native Developer"), "React Native")
        self.assertDrop(check(title="Mobile Engineer", desc="Our app is React Native and TypeScript."), "React Native only")
        self.assertDrop(check(title="iOS Engineer", desc="Swift and SwiftUI."), "iOS role")

    def test_graduate(self):
        self.assertDrop(check(title="Graduate Flutter Developer"), "graduate")
        self.assertDrop(check(desc="Join our 2026 graduate programme."), "graduate program")

    def test_salary(self):
        self.assertDrop(check(desc="Salary: AED 6,000 per month."), "salary")
        self.assertDrop(check(desc="Compensation: $1,500 / month."), "salary")


class Software(unittest.TestCase):
    def test_junior_title_kept(self):
        for t in ("Junior Backend Developer", "Software Engineer I", "Associate Software Engineer", "Jr. Full Stack Developer"):
            v = check(title=t)
            self.assertTrue(v.keep, f"{t}: {v.reason}")
            self.assertIn("General software role (not mobile or AI)", v.warnings)

    def test_low_years_kept(self):
        self.assertTrue(check(title="Python Developer", desc="1-2 years of experience with Django.").keep)

    def test_not_junior_dropped(self):
        self.assertIn("not junior", check(title="Backend Engineer", desc="3+ years of experience.").reason)
        self.assertIn("not junior", check(title="Senior Frontend Engineer").reason)
        self.assertIn("not junior", check(title="Full Stack Developer").reason)

    def test_senior_software_with_flutter_is_mobile(self):
        v = check(title="Senior Software Engineer", desc="Our Flutter app. Flutter, Firebase.")
        self.assertTrue(v.keep, v.reason)

    def test_mobile_scores_above_software(self):
        self.assertGreater(check(title="Flutter Developer").score, check(title="Junior Backend Developer").score)


class NotSalary(unittest.TestCase):
    def test_funding_round_ignored(self):
        self.assertTrue(check(desc="We raised $50M in 2025.").keep)

    def test_perk_stipends_are_not_salary(self):
        for desc in ("Home office stipend: $100 per month.",
                     "Monthly Stipend: USD $150 per month via a Brex Card.",
                     "A $500 learning budget every year.",
                     "Salary: AED 15,000 per month, plus a $50 internet allowance per month."):
            v = check(desc=desc)
            self.assertTrue(v.keep, f"{desc}: {v.reason}")

    def test_real_salaries_still_count(self):
        self.assertIn("~15k AED/mo", check(desc="Salary: AED 15,000 per month.").positives)
        self.assertIn("salary", check(desc="Salary: AED 5,000 per month.").reason)
        self.assertIn("salary", check(desc="Salary range: $20,000 - $25,000 per year.").reason)

    def test_unclear_amount_does_not_drop(self):
        self.assertTrue(check(desc="You get AED 3,000 per month for transport.").keep)

    def test_minimum_with_overpayment_is_a_warning(self):
        v = check(desc="From AED 6,000 per month. Overpayment depending on experience.")
        self.assertTrue(v.keep, v.reason)
        self.assertTrue(any("a minimum" in w for w in v.warnings))


if __name__ == "__main__":
    unittest.main()
