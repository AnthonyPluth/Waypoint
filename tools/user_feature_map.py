from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ".claude/skills/verify-waypoint/references"
OUT = ROOT / REFERENCES / "feature-map.md"
GOTCHAS = ROOT / REFERENCES / "feature-gotchas.md"
DOCS = "docs/src/content/docs/start"
DOCS_LINK = "../../../../docs/src/content/docs/start"
SETTINGS_DOCS = ("ai", "gmail", "import", "mcp", "offline", "reminders")
VIEWPORT_ORDER = ["phone", "desktop", "laptop", "wide", "zoomed"]


def exported_list(verify: str, name: str) -> list[str]:
    found = re.search(rf"export const {name} = \[(.*?)\];", verify, re.DOTALL)
    return re.findall(r'"([^"]+)"', found.group(1)) if found else []


def nav_labels(nav: str) -> dict[str, str]:
    return dict(re.findall(r'\{ page: "([^"]+)", label: "([^"]+)"', nav))


def nav_list(nav: str, name: str) -> list[str]:
    found = re.search(rf"const {name} = \[(.*?)\];", nav)
    return re.findall(r'"([^"]+)"', found.group(1)) if found else []


def nav_inside(nav: str) -> dict[str, str]:
    found = re.search(r"const INSIDE: Record<string, string> = \{(.*?)\};", nav)
    return dict(re.findall(r"(\w+): \"([^\"]+)\"", found.group(1))) if found else {}


def reach(page: str, labels: dict[str, str], tabs: list[str], more: list[str], inside: dict[str, str], own: list[str]) -> str:
    if page in own:
        return ("not a route of the app: an assistant's connection request, a page the server serves at /oauth/authorize; make verify opens "
                "it with a request it seeds first, so `goto` can't")
    if page in labels:
        phone = "the tab bar" if page in tabs else "tab bar > More" if page in more else "not in the tab bar"
        return f"desktop: the sidebar's {labels[page]}; phone: {phone}; URL `#{page}`; control `tools/control goto {page}`"
    if page in inside:
        return f"not in the navigation (it keeps {labels.get(inside[page], inside[page])} lit); URL `#{page}`; control `tools/control goto {page}`"
    return f"URL `#{page}`; control `tools/control goto {page}`"


def docs_line(page: str, root: Path = ROOT) -> str:
    path = root / DOCS / f"{page}.md"
    if page == "settings":
        pages = [(name, docs_front(root / DOCS / f"{name}.md")) for name in SETTINGS_DOCS if (root / DOCS / f"{name}.md").exists()]
        return "Its sections are described in " + ", ".join(f"[{front.get('title', name)}]({DOCS_LINK}/{name}.md)" for name, front in pages) + "."
    if not path.exists():
        return "No docs page of its own."
    front = docs_front(path)
    return f"{front.get('description', '')} Docs: [{front.get('title', page)}]({DOCS_LINK}/{page}.md)."


def docs_front(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^(title|description): (.*)$", path.read_text().split("---")[1], re.MULTILINE))


def flows(directory: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]


def gotchas(text: str, names: set[str]) -> tuple[dict[str, list[str]], list[str]]:
    out: dict[str, list[str]] = {}
    problems = []
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            if current not in names:
                problems.append(f"feature-gotchas.md: `## {current}` is not a page or flow name")
            elif current in out:
                problems.append(f"feature-gotchas.md: `## {current}` appears twice")
            out.setdefault(current, [])
        elif line.startswith("- ") and current:
            out[current].append(line[2:].strip())
        elif current is None:
            continue
        elif line.strip() and not line.startswith(("- ", "  ")):
            problems.append(f"feature-gotchas.md: only `- ` bullets go under a heading: {line[:50]!r}")
    return out, problems


def quoted(selector: str) -> list[str]:
    found = re.findall(r"""aria-label[\^*]?=(?:'([^']+)'|"([^"]+)")|(?:has-text|text-is)\((?:'([^']+)'|"([^"]+)")\)|text=(.+)$""", selector)
    return [next(x for x in f if x) for f in found]


def uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def summary(flow: dict, start: str = "") -> dict[str, list[str]]:
    routes, clicks, texts, fakes = [], [], [], []
    for step in flow["steps"]:
        if "goto" in step:
            routes.append(step["goto"])
        for key in ("click", "click_if_present", "hover", "fill", "press"):
            if key in step:
                target = step[key]["selector"] if isinstance(step[key], dict) else step[key]
                clicks += quoted(target)
        if "expect_text" in step:
            texts.append(step["expect_text"]["text"])
        fakes += [k for k in step if k.startswith("fake_") or k == "long_names"]
    return {"goes to": [r for r in uniq(routes) if r != start], "touches": uniq(clicks), "expects to see": uniq(texts), "fakes": uniq(fakes)}


def widths(flow: dict) -> list[str]:
    chosen = flow.get("viewports") or ["phone", "desktop"]
    return sorted(chosen, key=lambda v: VIEWPORT_ORDER.index(v) if v in VIEWPORT_ORDER else 99)


def code(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items)


def flow_lines(flow: dict, notes: dict[str, list[str]]) -> list[str]:
    name = flow["name"]
    start = f"#{flow.get('page', 'upcoming')}"
    s = summary(flow, start)
    lines = [f"#### `{name}`", "", f"- **Starts at:** `{start}`" + (f"; goes to: {code(s['goes to'])}" if s["goes to"] else "") + ".",
             f"- **Widths:** {', '.join(widths(flow))}."]
    if flow.get("host"):
        lines.append(f"- **Host:** `{flow['host']}` (a passkey needs a host name, not an IP address).")
    if flow.get("phone_agent"):
        lines.append("- **Looks like an iPhone** to the page at phone width (`phone_agent`).")
    if s["touches"]:
        lines.append(f"- **Touches:** {code(s['touches'])}.")
    if s["expects to see"]:
        lines.append(f"- **Expects to see:** {code(s['expects to see'])}.")
    if s["fakes"]:
        lines.append(f"- **Fakes (the demo server can't):** {code(s['fakes'])}.")
    if flow.get("allow_console"):
        lines.append(f"- **Console errors it expects:** {code(flow['allow_console'])}.")
    lines.append(f"- **Drive it:** `tools/control flow {name}`; or `poetry run python run.py verify --flow {name}`.")
    if notes.get(name):
        lines += ["- **What usually breaks:**", *[f"  - {n}" for n in notes[name]]]
    lines.append("")
    return lines


def render(page_names: list[str], labels: dict[str, str], tabs: list[str], more: list[str], inside: dict[str, str], own: list[str],
           all_flows: list[dict], notes: dict[str, list[str]], root: Path = ROOT) -> str:
    lines = [
        "# User feature map",
        "",
        "Generated by `tools/user_feature_map.py` (`make user-feature-map`); do not edit. The gotchas come from "
        "[feature-gotchas.md](feature-gotchas.md), which is hand-edited. `make fleet-checks` fails when this file is out of date.",
        "",
        "What a person can do in the web app, by page: what is there, how to reach it, how to drive it with `tools/control` "
        "(or `make verify`), and what usually breaks. It is not `docs/feature-map.json` (and its docs page, `make feature-map`), "
        "which goes by API route to find the code behind a feature: that map starts from a route and ends at a handler, a test and a docs "
        "page; this one starts from what a user sees, from the pages and flows `make verify` runs, and ends at the commands that drive it. "
        "All of it is demo data; `tools/control start` first, and `flow <name>` runs a flow's steps (after `reset` for the data "
        "`make verify` starts it from).",
        "",
    ]
    for page in page_names:
        label = labels.get(page, page)
        lines += [f"## {label} (`{page}`)", "", f"- **What exists:** {docs_line(page, root)}",
                  f"- **Reach it:** {reach(page, labels, tabs, more, inside, own)}."]
        if page not in own:
            lines.append(f"- **Drive it:** `tools/control goto {page}`, `tools/control snapshot --text`, then `click`/`type`/`press`; "
                         f"`tools/control viewport phone|desktop`; batch check `make verify PAGES=\"{page}\"`.")
        if notes.get(page):
            lines += ["- **What usually breaks:**", *[f"  - {n}" for n in notes[page]]]
        mine = [f for f in all_flows if f.get("page", "upcoming") == page]
        lines.append("")
        if mine:
            lines += [f"### Flows on {label}", ""]
        for flow in mine:
            lines += flow_lines(flow, notes)
    return "\n".join(lines).rstrip() + "\n"


def generate(root: Path = ROOT) -> tuple[str, list[str]]:
    verify = (root / "frontend/verify/verify.mjs").read_text()
    nav = (root / "frontend/src/lib/nav.ts").read_text()
    page_names = exported_list(verify, "PAGES")
    own = exported_list(verify, "OWN_PAGES")
    all_flows = flows(root / "frontend/verify/flows")
    names = set(page_names) | {f["name"] for f in all_flows}
    gotcha_file = root / REFERENCES / "feature-gotchas.md"
    notes, problems = gotchas(gotcha_file.read_text() if gotcha_file.exists() else "", names)
    if not page_names:
        problems.append("no PAGES found in frontend/verify/verify.mjs")
    text = render(page_names, nav_labels(nav), nav_list(nav, "TAB_PAGES"), nav_list(nav, "MORE_PAGES"), nav_inside(nav), own, all_flows, notes, root)
    return text, problems


def check(committed: str | None, generated: str) -> list[str]:
    name = str(OUT.relative_to(ROOT))
    if committed is None:
        return [f"{name}: missing; run make user-feature-map and commit it"]
    if committed != generated:
        return [f"{name} isn't what tools/user_feature_map.py generates: run make user-feature-map and commit the result "
                "(hand-written advice goes in references/feature-gotchas.md, never in the generated file)"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="write nothing; fail when the committed file is out of date")
    args = ap.parse_args(argv)
    text, problems = generate()
    if not args.check and not problems:
        OUT.write_text(text)
    if args.check:
        problems += check(OUT.read_text() if OUT.exists() else None, text)
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
