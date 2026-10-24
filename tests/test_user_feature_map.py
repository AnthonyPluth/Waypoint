import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("user_feature_map", ROOT / "tools" / "user_feature_map.py")
assert _spec and _spec.loader
ufm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ufm)

NAV = '''export const NAV: NavItem[] = [
  { page: "upcoming", label: "Upcoming", icon: PlaneTakeoff },
  { page: "trips", label: "Trips", icon: Luggage },
  { page: "settings", label: "Settings", icon: Settings },
];

const TAB_PAGES = ["upcoming", "trips"];
const MORE_PAGES = ["settings"];
const INSIDE: Record<string, string> = { trip: "trips", design: "settings" };
'''
FLOW = {"name": "trip-edit", "page": "trips", "viewports": ["desktop", "phone"], "host": "localhost", "steps": [
    {"goto": "#trips"}, {"goto": "#settings/offline"}, {"fake_labels": "Japan"},
    {"click": "button[aria-label^='Edit Harbour Hotel']"},
    {"click_if_present": "[role=dialog] button:text-is('Cancel')"},
    {"expect_text": {"selector": "body", "text": "Harbour Hotel"}}]}


class Reading(unittest.TestCase):
    def test_pages_and_nav_come_from_the_code(self):
        self.assertEqual(ufm.exported_list('export const PAGES = ["upcoming", "trips"];', "PAGES"), ["upcoming", "trips"])
        self.assertEqual(ufm.exported_list("", "PAGES"), [])
        self.assertEqual(ufm.nav_labels(NAV), {"upcoming": "Upcoming", "trips": "Trips", "settings": "Settings"})
        self.assertEqual(ufm.nav_list(NAV, "TAB_PAGES"), ["upcoming", "trips"])
        self.assertEqual(ufm.nav_list(NAV, "MORE_PAGES"), ["settings"])
        self.assertEqual(ufm.nav_inside(NAV), {"trip": "trips", "design": "settings"})

    def test_a_flow_is_summed_up_by_what_it_visits_touches_expects_and_fakes(self):
        self.assertEqual(ufm.summary(FLOW, "#trips"), {"goes to": ["#settings/offline"], "touches": ["Edit Harbour Hotel", "Cancel"],
                                                       "expects to see": ["Harbour Hotel"], "fakes": ["fake_labels"]})
        self.assertEqual(ufm.widths(FLOW), ["phone", "desktop"])

    def test_both_quote_styles_are_read(self):
        self.assertEqual(ufm.quoted("button[aria-label^=\"Details for \"]"), ["Details for "])
        self.assertEqual(ufm.quoted("button:has-text(\"Add a booking\")"), ["Add a booking"])
        self.assertEqual(ufm.quoted("button:text-is('Save')"), ["Save"])

    def test_reach_differs_for_a_tab_a_more_page_a_page_inside_another_and_the_assistant_page(self):
        labels, tabs, more, inside = ufm.nav_labels(NAV), ["upcoming", "trips"], ["settings"], ufm.nav_inside(NAV)
        self.assertIn("phone: the tab bar", ufm.reach("trips", labels, tabs, more, inside, []))
        self.assertIn("phone: tab bar > More", ufm.reach("settings", labels, tabs, more, inside, []))
        self.assertIn("keeps Settings lit", ufm.reach("design", labels, tabs, more, inside, []))
        self.assertIn("can't", ufm.reach("oauth-approve", labels, tabs, more, inside, ["oauth-approve"]))


class Gotchas(unittest.TestCase):
    def test_bullets_are_merged_under_their_name(self):
        notes, problems = ufm.gotchas("# T\n\nintro\n\n## trips\n- one\n- two\n\n## trip-edit\n- three\n", {"trips", "trip-edit"})
        self.assertEqual((notes, problems), ({"trips": ["one", "two"], "trip-edit": ["three"]}, []))

    def test_a_name_that_is_no_page_or_flow_a_repeat_or_loose_text_is_a_problem(self):
        _, problems = ufm.gotchas("## gone\n- x\n", {"trips"})
        self.assertIn("`## gone` is not a page or flow name", problems[0])
        _, problems = ufm.gotchas("## trips\n- x\n## trips\n- y\n", {"trips"})
        self.assertIn("appears twice", problems[0])
        _, problems = ufm.gotchas("## trips\nloose text\n", {"trips"})
        self.assertIn("only `- ` bullets", problems[0])


class Rendering(unittest.TestCase):
    def render(self, notes):
        with tempfile.TemporaryDirectory() as tmp:
            return ufm.render(["trips", "oauth-approve"], ufm.nav_labels(NAV), ["trips"], [], {}, ["oauth-approve"], [FLOW], notes, Path(tmp))

    def test_a_page_and_its_flow_say_how_to_reach_and_drive_them(self):
        text = self.render({"trips": ["Wait for it."], "trip-edit": ["Cancel it."]})
        for want in ("## Trips (`trips`)", "tools/control goto trips", "### Flows on Trips", "#### `trip-edit`", "tools/control flow trip-edit",
                     "run.py verify --flow trip-edit", "`localhost`", "`fake_labels`", "  - Wait for it.", "  - Cancel it.", "It is not `docs/feature-map.json`"):
            self.assertIn(want, text)
        self.assertNotIn("tools/control goto oauth-approve", text)

    def test_the_header_says_how_it_differs_from_the_route_map(self):
        self.assertIn("goes by API route", self.render({}))

    def test_docs_links_lead_to_the_page_files_from_where_the_map_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / ufm.DOCS
            docs.mkdir(parents=True)
            (docs / "trips.md").write_text("---\ntitle: Trips\ndescription: How trips work.\n---\nBody\n")
            self.assertEqual(ufm.docs_line("trips", Path(tmp)), f"How trips work. Docs: [Trips]({ufm.DOCS_LINK}/trips.md).")
            self.assertEqual(ufm.docs_line("upcoming", Path(tmp)), "No docs page of its own.")
        target = (ROOT / ufm.REFERENCES / ufm.DOCS_LINK).resolve()
        self.assertEqual(target, (ROOT / ufm.DOCS).resolve())


class Committed(unittest.TestCase):
    def test_the_inputs_are_sound_and_the_committed_file_is_current(self):
        text, problems = ufm.generate()
        self.assertEqual(problems, [])
        self.assertEqual(ufm.check(ufm.OUT.read_text(), text), [])

    def test_a_stale_or_missing_file_is_named(self):
        self.assertIn("make user-feature-map", ufm.check("old", "new")[0])
        self.assertIn("missing", ufm.check(None, "new")[0])
        self.assertEqual(ufm.check("same", "same"), [])

    def test_every_page_and_flow_is_in_the_file_and_every_docs_link_exists(self):
        text, _ = ufm.generate()
        for page in ufm.exported_list((ROOT / "frontend/verify/verify.mjs").read_text(), "PAGES"):
            self.assertIn(f"(`{page}`)", text)
        for flow in ufm.flows(ROOT / "frontend/verify/flows"):
            self.assertIn(f"#### `{flow['name']}`", text)
        for link in re.findall(r"\]\((\.\./[^)]+\.md)\)", text):
            self.assertTrue((ROOT / ufm.REFERENCES / link).resolve().exists(), link)


if __name__ == "__main__":
    unittest.main()
