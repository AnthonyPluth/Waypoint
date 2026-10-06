from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = (".semgrep/examples/", "node_modules/")
PY_DIRECTIVE = re.compile(r"#\s*(noqa|type:|pragma|nosemgrep|nosec|fmt:|isort|ruff:|pyright|mypy|pylint|-\*-|coding[:=])")
CSS_COMMENT = re.compile(r"/\*(?!!|\s*stylelint-)[\s\S]*?\*/")
STYLE_BLOCK = re.compile(r"<style\b[^>]*>([\s\S]*?)</style>")


def python_comments(source: str) -> list[int]:
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        if tok.start[0] == 1 and tok.string.startswith("#!"):
            continue
        if PY_DIRECTIVE.match(tok.string):
            continue
        found.append(tok.start[0])
    return found


def python_docstrings(source: str) -> list[int]:
    return sorted(node.lineno for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))


def css_comments(source: str) -> list[int]:
    return [source.count("\n", 0, m.start()) + 1 for m in CSS_COMMENT.finditer(source)]


def svelte_style_comments(source: str) -> list[int]:
    found = []
    for block in STYLE_BLOCK.finditer(source):
        offset = source.count("\n", 0, block.start(1))
        found += [offset + line for line in css_comments(block.group(1))]
    return found


def problems(path: str, source: str) -> list[str]:
    if path.endswith(".py"):
        lines = python_comments(source) + python_docstrings(source)
    elif path.endswith(".css"):
        lines = css_comments(source)
    elif path.endswith(".svelte"):
        lines = svelte_style_comments(source)
    else:
        return []
    return [f"{path}:{n}: a comment or docstring: say it in the code's names, or in the commit message or docs" for n in lines]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p and not any(s in p for s in SKIP)]


def main() -> int:
    found: list[str] = []
    for path in tracked_files():
        if path.endswith((".py", ".css", ".svelte")):
            found += problems(path, (ROOT / path).read_text(encoding="utf-8"))
    for line in found:
        print(line, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
