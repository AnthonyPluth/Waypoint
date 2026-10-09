from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_FILE = ROOT / "waypoint/server/routes.py"
JSON_OUT = ROOT / "docs/feature-map.json"
PAGE_OUT = ROOT / "docs/src/content/docs/contributing/feature-map.md"
ALLOWLIST = ROOT / "tools/feature_map_allowlist.txt"
DOCS = ROOT / "docs/src/content/docs"

AREA_DOCS = {
    "ai": "start/ai", "state": "start/docker", "mailboxes": "start/gmail", "backup": "start/docker", "restore": "start/docker",
    "people": "start/people", "loyalty": "start/loyalty", "review": "start/review",
    "trips": "start/trips", "segments": "start/trips", "import": "start/import", "airports": "start/trips", "flight-status": "start/flight-status", "logodev": "start/logos",
    "reminders": "start/reminders", "feed": "start/reminders",
    "stats": "start/stats", "mcp-settings": "start/mcp", "offline": "start/offline",
}

CALL = re.compile(r"\b(?:apiCall|api|fetch|EventSource)\s*(?:<[^>(]*>)?\(\s*([`\"'])(/api/[^`\"']*)\1")
TEST_PATH = re.compile(r"""["'`](/api/[^"'`\s?#]*)""")
VERBS = re.compile(r"\b(GET|POST|DELETE|get|post|delete)\b")


def routes() -> list[dict]:
    tree = ast.parse(ROUTES_FILE.read_text())
    modules: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module and node.module.startswith("api."):
            for alias in node.names:
                modules[alias.asname or alias.name] = "waypoint/server/" + node.module.replace(".", "/") + ".py"
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "ROUTES" and isinstance(node.value, ast.List):
            found = []
            for e in node.value.elts:
                m, p, f = e.elts   # type: ignore[attr-defined]
                found.append({"method": m.value, "path": p.value, "handler": f.id, "file": modules[f.id]})
            return found
    raise SystemExit("tools/feature_map.py: ROUTES not found in waypoint/server/routes.py")


def segments(path: str) -> list[str]:
    return ["{id}" if s.startswith("{") or "${" in s else s for s in path.strip("/").split("/")]


def answers(rs: list[dict], method: str | None, path: str) -> list[dict]:
    parts = segments(path)
    found: dict[str, dict] = {}
    for r in rs:
        want = r["parts"]
        if (method is not None and method != r["method"]) or r["method"] in found or len(want) != len(parts):
            continue
        if all(w == "{id}" if g == "{id}" else w in (g, "{id}") for w, g in zip(want, parts, strict=True)):
            found[r["method"]] = r
    return list(found.values())


def call_method(text: str, start: int) -> str | None:
    depth, end = 0, min(len(text), start + 800)
    for i in range(text.index("(", start), end):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            end = i
            break
    call = text[start:end]
    m = re.search(r"""method:\s*["'`](\w+)["'`]""", call)
    if m:
        return m.group(1).upper()
    return None if re.search(r"\bmethod\b", call) else "GET"


def web_callers(rs: list[dict]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for f in sorted((ROOT / "frontend/src").rglob("*")):
        if f.suffix not in (".svelte", ".ts") or ".test." in f.name or "/test/" in f.as_posix():
            continue
        text = f.read_text()
        for m in CALL.finditer(text):
            path = re.sub(r"\$\{[^}]*\}", "{id}", m.group(2)).split("?")[0]
            for r in answers(rs, call_method(text, m.start()), path):
                out.setdefault((r["method"], r["path"]), set()).add(f.relative_to(ROOT).as_posix())
    return out


def test_users(rs: list[dict]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for f in sorted((ROOT / "tests").glob("*.py")):
        text = f.read_text()
        rel = f.relative_to(ROOT).as_posix()
        for r in rs:
            if re.search(rf"\b{r['handler']}\b", text):
                out.setdefault((r["method"], r["path"]), set()).add(rel)
        for m in TEST_PATH.finditer(text):
            path = re.sub(r"\{[^}]*\}", "{id}", m.group(1))
            verb = VERBS.findall(text[max(0, m.start() - 120):m.start()])
            for r in answers(rs, verb[-1].upper() if verb else None, path):
                out.setdefault((r["method"], r["path"]), set()).add(rel)
    return out


def docs_for(r: dict, pages: dict[str, str]) -> list[str]:
    named = sorted(p for p, text in pages.items() if r["path"] in text or re.search(rf"\b{r['handler']}\b", text))
    if named:
        return named
    area = segments(r["path"])[1]
    return [AREA_DOCS[area]] if area in AREA_DOCS else []


def build() -> dict:
    rs = routes()
    for r in rs:
        r["parts"] = segments(r["path"])
    web, tests = web_callers(rs), test_users(rs)
    pages = {p.relative_to(DOCS).with_suffix("").as_posix(): p.read_text() for p in sorted(DOCS.rglob("*.md*"))
             if p != PAGE_OUT}
    return {"routes": [{
        "method": r["method"], "path": r["path"], "handler": f"{r['file']}:{r['handler']}",
        "web": sorted(web.get((r["method"], r["path"]), ())),
        "tests": sorted(tests.get((r["method"], r["path"]), ())),
        "docs": docs_for(r, pages),
    } for r in rs]}


def render_json(fm: dict) -> str:
    return json.dumps(fm, indent=2, ensure_ascii=False) + "\n"


def render_page(fm: dict, allowed: set[str]) -> str:
    rows = fm["routes"]
    untested = [r for r in rows if not r["tests"]]
    lines = [
        "---", "title: Feature map",
        "description: Every API route, with its handler, the web app files that call it, its tests and its docs page.",
        "---", "",
        "<!-- Generated by tools/feature_map.py (`make feature-map`); don't edit by hand. -->", "",
        "Where each feature lives. Every route in `waypoint/server/routes.py` is listed with its handler, the web app files that call it, the tests that exercise it and the docs page that describes it. "
        "The same data, for tools and agents, is in [`docs/feature-map.json`](https://github.com/AnthonyPluth/waypoint/blob/main/docs/feature-map.json). "
        "`make feature-map` regenerates both; `make check` and CI fail when they are out of date, or when a route has no test and isn't on `tools/feature_map_allowlist.txt` (a list that only shrinks).", "",
        f"{len(rows)} routes; {len(untested)} have no test yet.", "",
        "A route counts as tested when a file in `tests/` names its handler, or calls its address (with its method, when the test writes one). "
        "A web app caller is an `api(` or `apiCall(` call with a literal address; one built in a variable isn't seen.", "",
        "| Route | Handler | Web app | Tests | Docs |", "| --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        key = f"{r['method']} {r['path']}"
        tests = ", ".join(f"`{t.removeprefix('tests/')}`" for t in r["tests"]) or ("none (allowed)" if key in allowed else "**none**")
        web = ", ".join(f"`{w.removeprefix('frontend/src/')}`" for w in r["web"]) or "-"
        docs = ", ".join(f"[{d}](/Waypoint/{d}/)" for d in r["docs"]) or "-"
        lines.append(f"| `{key}` | `{r['handler'].replace('waypoint/server/api/', '')}` | {web} | {tests} | {docs} |")
    return "\n".join(lines) + "\n"


def read_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    return {ln.strip() for ln in ALLOWLIST.read_text().splitlines() if ln.strip() and not ln.startswith("#")}


ALLOW_HEADER = """# Routes that have no test yet, as "METHOD /path" (see tools/feature_map.py). `make check` fails for a route with no
# test that isn't here, and for a line here whose route has a test or is gone: this list only shrinks. Add a test and
# delete its line; never add a line for a new route.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="write nothing; fail if the map is out of date or a route has no test")
    ap.add_argument("--write-allowlist", action="store_true", help="(re)write the allow-list from the routes with no test now")
    args = ap.parse_args()
    fm = build()
    untested = {f"{r['method']} {r['path']}" for r in fm["routes"] if not r["tests"]}
    if args.write_allowlist:
        ALLOWLIST.write_text(ALLOW_HEADER + "".join(k + "\n" for k in sorted(untested)))
    allowed = read_allowlist()
    want = {JSON_OUT: render_json(fm), PAGE_OUT: render_page(fm, allowed)}
    if not args.check:
        for f, text in want.items():
            f.write_text(text)
        return 0
    problems = [f"{f.relative_to(ROOT)} is out of date: run `make feature-map`" for f, text in want.items()
                if not f.exists() or f.read_text() != text]
    problems += [f"no test exercises {k}: add one (the allow-list only shrinks)" for k in sorted(untested - allowed)]
    problems += [f"tools/feature_map_allowlist.txt lists {k}, which now has a test or is gone: delete the line"
                 for k in sorted(allowed - untested)]
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
