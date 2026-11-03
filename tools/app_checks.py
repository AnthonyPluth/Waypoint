from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

PARSERS = "waypoint/domain/mail/parsers"
MAIL_FIXTURES = "tests/fixtures/mail"
TESTS = "tests"
PARSER_FIXTURES = ("booking", "change", "cancellation")

LIGHT_THEME = re.compile(r"prefers-color-scheme|color-scheme\s*:[^;}]*\blight\b|name=[\"']color-scheme[\"'][^>]*content=[\"'][^\"']*\blight\b")
THEMED_FILES = ("frontend/index.html", "frontend/src/**/*.css", "waypoint/static/*.css")

LINKS = "waypoint/domain/links.py"
LINKS_TESTS = "tests/test_links.py"
BARE_HOST = re.compile(r"[a-z0-9.-]+\.[a-z]{2,}")


def parser_vendors(directory: Path) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.py") if not p.stem.startswith("_"))


def check_parsers(vendors: list[str], registry: str, fixtures: Path, tests: Path) -> list[str]:
    problems = []
    for vendor in vendors:
        where = f"{PARSERS}/{vendor}.py"
        if not re.search(rf"\b{re.escape(vendor)}\.parse\b", registry):
            problems.append(f"{where}: not registered in PARSERS in parsers/__init__.py (a parser nothing runs)")
        for name in PARSER_FIXTURES:
            if not (fixtures / vendor / f"{name}.eml").is_file():
                problems.append(f"{where}: no synthetic fixture {MAIL_FIXTURES}/{vendor}/{name}.eml")
        test = tests / f"test_mail_parser_{vendor}.py"
        if not test.is_file():
            problems.append(f"{where}: no test in tests/test_mail_parser_{vendor}.py that uses the fixtures")
            continue
        text = test.read_text(encoding="utf-8")
        if not re.search(rf"""fixtures/mail/{re.escape(vendor)}\b|"fixtures"\s*/\s*"mail"\s*/\s*"{re.escape(vendor)}\"""", text):
            problems.append(f"{test.name}: doesn't name the fixtures directory {MAIL_FIXTURES}/{vendor}/")
        for name in PARSER_FIXTURES:
            if not re.search(rf"""["']{name}["']""", text):
                problems.append(f"{test.name}: never uses the {name} fixture")
    return problems


def mail_parsers(context: Any) -> list[str]:
    root: Path = context.root
    parsers = root / PARSERS
    return check_parsers(parser_vendors(parsers), (parsers / "__init__.py").read_text(encoding="utf-8"),
                         root / MAIL_FIXTURES, root / TESTS)


def dark_only_files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for pattern in THEMED_FILES for p in sorted(root.glob(pattern)) if p.is_file()}


def check_dark_only(files: dict[str, str]) -> list[str]:
    return [f"{name}: the app is dark only, so no light palette and no prefers-color-scheme (tokens live in frontend/src/app.css)"
            for name, text in files.items() if LIGHT_THEME.search(text)]


def dark_only(context: Any) -> list[str]:
    return check_dark_only(dark_only_files(context.root))


def manage_table(source: str) -> dict[str, tuple[str, str]]:
    tree = ast.parse(source)
    names: dict[str, object] = {}
    table: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        value = getattr(node, "value", None)
        if not isinstance(target, ast.Name) or value is None:
            continue
        if target.id == "MANAGE":
            if not isinstance(value, ast.Dict):
                raise ValueError(f"{LINKS}: MANAGE isn't a dict literal")
            for key, item in zip(value.keys, value.values, strict=True):
                provider = ast.literal_eval(key) if key is not None else None
                entry = names[item.id] if isinstance(item, ast.Name) else ast.literal_eval(item)
                if not isinstance(provider, str) or not isinstance(entry, tuple) or len(entry) != 2:
                    raise ValueError(f"{LINKS}: MANAGE entries are provider -> (host, path)")
                table[provider] = (str(entry[0]), str(entry[1]))
        else:
            try:
                names[target.id] = ast.literal_eval(value)
            except ValueError:
                continue
    return table


def check_manage_links(table: dict[str, tuple[str, str]], tests_text: str) -> list[str]:
    problems = []
    for provider, (host, _path) in table.items():
        if not BARE_HOST.fullmatch(host):
            problems.append(f"manage link for {provider!r}: {host!r} isn't a bare host")
        if f'"{provider}"' not in tests_text and f"'{provider}'" not in tests_text:
            problems.append(f"manage link for {provider!r} has no test in {LINKS_TESTS}")
    return problems


def manage_links(context: Any) -> list[str]:
    root: Path = context.root
    try:
        table = manage_table((root / LINKS).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, KeyError) as error:
        return [f"{LINKS}: couldn't read MANAGE ({error})"]
    return check_manage_links(table, (root / LINKS_TESTS).read_text(encoding="utf-8"))


CHECKS = [mail_parsers, dark_only, manage_links]
