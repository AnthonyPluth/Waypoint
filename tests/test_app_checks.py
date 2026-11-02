import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools import app_checks as ac

ROOT = Path(__file__).resolve().parent.parent


def context(root=ROOT):
    return SimpleNamespace(root=root, config=None, commits=None)


class Checks(unittest.TestCase):
    def test_the_repository_passes_every_check(self):
        for check in ac.CHECKS:
            self.assertEqual(check(context()), [], check.__name__)

    def test_the_three_checks_are_registered(self):
        self.assertEqual([c.__name__ for c in ac.CHECKS], ["mail_parsers", "dark_only", "manage_links"])


class MailParsers(unittest.TestCase):
    REGISTRY = "PARSERS = {'acme.com': acme.parse}\n"
    TEST = 'FIXTURES = Path(__file__).parent / "fixtures" / "mail" / "acme"\nraw("booking"); raw("change"); raw("cancellation")\n'

    def problems(self, vendors=("acme",), registry=REGISTRY, fixtures=("booking", "change", "cancellation"), test=TEST, name="acme"):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "fixtures" / "acme").mkdir(parents=True)
            for f in fixtures:
                (root / "fixtures" / "acme" / f"{f}.eml").write_text("From: a\n\nbody")
            if test is not None:
                (root / f"test_mail_parser_{name}.py").write_text(test)
            return ac.check_parsers(list(vendors), registry, root / "fixtures", root)

    def test_the_repository_passes(self):
        vendors = ac.parser_vendors(ROOT / ac.PARSERS)
        self.assertIn("southwest", vendors)
        self.assertNotIn("_text", vendors)
        self.assertNotIn("__init__", vendors)
        self.assertEqual(ac.mail_parsers(context()), [])

    def test_a_parser_with_fixtures_and_a_test_passes(self):
        self.assertEqual(self.problems(), [])

    def test_no_parsers_need_nothing(self):
        self.assertEqual(self.problems(vendors=()), [])

    def test_a_parser_nothing_runs_fails(self):
        [problem] = self.problems(registry="PARSERS = {'other.com': other.parse}\n")
        self.assertIn("not registered", problem)

    def test_a_missing_fixture_fails_for_each_one_missing(self):
        problems = self.problems(fixtures=("booking",))
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("change.eml" in p for p in problems) and any("cancellation.eml" in p for p in problems))

    def test_no_test_fails(self):
        [problem] = self.problems(test=None)
        self.assertIn("test_mail_parser_acme.py", problem)

    def test_a_test_that_doesnt_name_the_fixtures_or_use_each_of_them_fails(self):
        problems = self.problems(test='raw("booking")\n')
        self.assertEqual(len(problems), 3)
        self.assertIn("fixtures directory", problems[0])
        self.assertTrue(any("change fixture" in p for p in problems) and any("cancellation fixture" in p for p in problems))

    def test_the_directory_can_be_named_as_a_path(self):
        text = '"""Reads tests/fixtures/mail/acme."""\nraw("booking"); raw(\'change\'); raw("cancellation")\n'
        self.assertEqual(self.problems(test=text), [])

    def test_a_parser_missing_everything_is_reported_through_the_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ac.PARSERS).mkdir(parents=True)
            (root / ac.PARSERS / "__init__.py").write_text("PARSERS = {}\n")
            (root / ac.PARSERS / "acme.py").write_text("def parse(m): ...\n")
            (root / ac.TESTS).mkdir()
            problems = ac.mail_parsers(context(root))
        self.assertEqual(len(problems), 5)
        self.assertTrue(all(p.startswith("waypoint/domain/mail/parsers/acme.py") for p in problems))


class DarkOnly(unittest.TestCase):
    def test_the_repository_passes(self):
        files = ac.dark_only_files(ROOT)
        self.assertIn("frontend/index.html", files)
        self.assertIn("frontend/src/app.css", files)
        self.assertIn("waypoint/static/page.css", files)
        self.assertEqual(ac.dark_only(context()), [])

    def test_a_prefers_color_scheme_query_fails(self):
        problems = ac.check_dark_only({"frontend/src/x.css": "@media (prefers-color-scheme: light) { :root { --bg: #fff } }"})
        self.assertEqual(len(problems), 1)
        self.assertIn("frontend/src/x.css: the app is dark only", problems[0])

    def test_a_stylesheet_or_meta_tag_that_allows_light_fails(self):
        self.assertEqual(len(ac.check_dark_only({"a.css": ":root { color-scheme: light dark; }"})), 1)
        self.assertEqual(len(ac.check_dark_only({"i.html": '<meta name="color-scheme" content="light dark">'})), 1)
        self.assertEqual(len(ac.check_dark_only({"i.html": '<meta name="color-scheme" content="dark">'})), 0)

    def test_dark_only_passes(self):
        self.assertEqual(ac.check_dark_only({"a.css": ":root { color-scheme: dark; --bg: #07090e }"}), [])

    def test_a_light_stylesheet_in_the_tree_is_found_by_the_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "frontend/src").mkdir(parents=True)
            (root / "frontend/src/light.css").write_text("@media (prefers-color-scheme: light) {}")
            [problem] = ac.dark_only(context(root))
        self.assertTrue(problem.startswith("frontend/src/light.css"))


class ManageLinks(unittest.TestCase):
    def test_a_provider_needs_a_test_and_a_bare_host(self):
        table = {"example air": ("www.example.com", "/m?c={code}")}
        self.assertEqual(ac.check_manage_links(table, 'x("example air")'), [])
        self.assertIn("has no test", ac.check_manage_links(table, "")[0])
        self.assertIn("isn't a bare host", ac.check_manage_links({"a": ("evil.com/x", "/")}, '"a"')[0])
        self.assertEqual(ac.check_manage_links({}, ""), [])

    def test_the_table_is_read_from_the_source_with_its_named_entries(self):
        source = 'X = ("www.x.com", "/a")\nMANAGE: dict[str, tuple[str, str]] = {"x air": X, "y": ("www.y.com", "/b")}\n'
        self.assertEqual(ac.manage_table(source), {"x air": ("www.x.com", "/a"), "y": ("www.y.com", "/b")})

    def test_the_repository_s_table_is_read_and_passes(self):
        table = ac.manage_table((ROOT / ac.LINKS).read_text())
        self.assertIn("southwest airlines", table)
        self.assertEqual(ac.manage_links(context()), [])

    def test_a_table_that_isnt_a_literal_is_a_problem_not_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "waypoint/domain").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / ac.LINKS).write_text("MANAGE = build()\n")
            (root / ac.LINKS_TESTS).write_text("")
            [problem] = ac.manage_links(context(root))
        self.assertIn("couldn't read MANAGE", problem)
