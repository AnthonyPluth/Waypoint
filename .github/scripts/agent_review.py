from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MARKER = "<!-- agent-review -->"
STATE = re.compile(r"^<!-- agent-review-state sha=([0-9a-f]{40}) verdict=(pass|blocking) -->$", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")
SESSION = re.compile(r"^claude-session:\s*\S", re.IGNORECASE | re.MULTILINE)
CO_AUTHOR = re.compile(r"^co-authored-by:.*(\bclaude\b|anthropic\.com)", re.IGNORECASE | re.MULTILINE)
BODY_SIGNS = ("Generated with [Claude Code]", "claude.ai/code/session_")
SEVERITIES = ("blocking", "advisory")
MAX_COMMENT = 60000
SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

GENERATED = ("docs/openapi.json", "frontend/src/lib/api-types.ts", "docs/feature-map.json",
             "docs/src/content/docs/contributing/feature-map.md")
LOCKFILES = ("poetry.lock", "uv.lock", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".heic", ".bmp", ".tif", ".tiff")
SAMPLE_DATA = re.compile(r"(^|/)tests/|fixture|demo|sample|example|seed", re.IGNORECASE)

USAGE = """usage:
  agent_review.py detect                          commit messages (JSON lines) on stdin, $BODY: true or false
  agent_review.py previous COMMENTS.jsonl OUT.md  the last review's commit and verdict, its text to OUT.md
  agent_review.py plan                            gather the change into $OUT_DIR; mode, description, incremental
  agent_review.py report OUT.json                 the reviewer's answer as the verdict, description and comment"""


def is_agent(messages: list[str], body: str) -> bool:
    if any(sign in body for sign in BODY_SIGNS):
        return True
    return any(SESSION.search(m) or CO_AUTHOR.search(m) for m in messages)


def previous(bodies: list[str]) -> tuple[str, str, str]:
    for body in bodies:
        if not body.startswith(MARKER):
            continue
        lines = body.splitlines()
        m = STATE.match(lines[1]) if len(lines) > 1 else None
        if not m:
            return "", "", ""
        return m.group(1), m.group(2), "\n".join(lines[2:]).strip() + "\n"
    return "", "", ""


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def is_image(path: str) -> bool:
    return path.lower().endswith(IMAGES)


def left_out(path: str) -> bool:
    if path.startswith(".github/"):
        return False
    if is_image(path):
        return True
    if SAMPLE_DATA.search(path):
        return False
    return path in GENERATED or path.rsplit("/", 1)[-1] in LOCKFILES


def diff(repo: str, *revs: str, paths: list[str] | None = None, exclude: list[str] | None = None) -> str:
    spec = [f":(literal){p}" for p in paths] if paths is not None else ["."]
    spec += [f":(exclude,literal){p}" for p in exclude or []]
    return git(repo, "diff", "--no-ext-diff", "--no-textconv", *revs, "--", *spec)


def own_files(repo: str, main: str, rev: str) -> list[str]:
    out = git(repo, "diff", "--no-renames", "--name-only", "-z", f"{main}...{rev}")
    return [p for p in out.split("\0") if p]


def is_ancestor(repo: str, old: str, new: str) -> bool:
    if not (SHA.match(old) and SHA.match(new)) or old == new:
        return False
    return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", old, new], capture_output=True).returncode == 0


def own_change(repo: str, main: str, rev: str) -> str:
    return git(repo, "diff", "--no-ext-diff", "--no-textconv", "--full-index", "--binary", f"{main}...{rev}")


def only_main_merged(repo: str, main: str, prev: str, head: str) -> bool:
    if not is_ancestor(repo, prev, head):
        return False
    added = git(repo, "rev-list", "--parents", f"{prev}..{head}", f"^{main}").splitlines()
    if not added or any(len(line.split()) < 3 for line in added):
        return False
    if sorted(own_files(repo, main, prev)) != sorted(own_files(repo, main, head)):
        return False
    return own_change(repo, main, prev) == own_change(repo, main, head)


def plan(env: dict[str, str]) -> dict[str, str]:
    repo, out, main, head = env["REPO_DIR"], Path(env["OUT_DIR"]), env["MAIN"], env["HEAD"]
    omitted = [p for p in own_files(repo, main, head) if left_out(p)]
    (out / "diff.patch").write_text(diff(repo, f"{main}...{head}", exclude=omitted))
    (out / "omitted.txt").write_text("".join(p + "\n" for p in omitted))
    (out / "files.txt").write_text(git(repo, "diff", "--name-status", f"{main}...{head}"))
    (out / "commits.txt").write_text(git(repo, "log", "--format=commit %H%n%B", f"{main}..{head}"))
    result = {"mode": "review", "description": "", "incremental": "false"}
    prev = env.get("PREV_SHA", "")
    try:
        if env.get("PREV_VERDICT") == "pass" and env.get("PREV_STATE") == "success" \
                and only_main_merged(repo, main, prev, head):
            return {**result, "mode": "carry",
                    "description": f"Carried forward from the review of {prev[:7]}: only main merged in since"}
    except Exception as e:
        print(f"::warning::Reviewing again: couldn't compare with the last review ({type(e).__name__}).")
    try:
        body = Path(env["PREV_BODY"]).read_text() if env.get("PREV_BODY") else ""
        if body and is_ancestor(repo, prev, head):
            files = sorted(p for p in set(own_files(repo, main, head)) | set(own_files(repo, main, prev))
                           if not left_out(p))
            since = diff(repo, prev, head, paths=files) if files else ""
            (out / "since-last-review.patch").write_text(since)
            (out / "previous-review.md").write_text(body)
            with open(out / "prompt.md", "a", encoding="utf-8") as f:
                f.write("\n" + Path(env["TRUSTED"], "incremental.md").read_text())
            result["incremental"] = "true"
    except Exception as e:
        print(f"::warning::Reviewing the whole change: the re-review couldn't be prepared ({type(e).__name__}).")
        for name in ("since-last-review.patch", "previous-review.md"):
            (out / name).unlink(missing_ok=True)
        result["incremental"] = "false"
    return result


def structured(output: dict) -> dict | None:
    if isinstance(output.get("structured_output"), dict):
        return output["structured_output"]
    text = output.get("result")
    if not isinstance(text, str):
        return None
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    for candidate in [text, *reversed(blocks)]:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def findings_of(answer: dict) -> list[dict] | None:
    found = answer.get("findings")
    if not isinstance(found, list):
        return None
    out = []
    for f in found:
        if not isinstance(f, dict) or f.get("severity") not in SEVERITIES or not isinstance(f.get("title"), str):
            return None
        out.append(f)
    return out


def defuse(text: object, limit: int = 4000) -> str:
    s = str(text or "").replace("@", "@​").replace("<!--", "&lt;!--")
    return s if len(s) <= limit else s[:limit] + " …"


def render(findings: list[dict], summary: str, run_url: str, sha: str = "") -> str:
    blocking = [f for f in findings if f["severity"] == "blocking"]
    advisory = [f for f in findings if f["severity"] == "advisory"]
    lines = [MARKER]
    if SHA.match(sha):
        lines.append(f"<!-- agent-review-state sha={sha} verdict={'blocking' if blocking else 'pass'} -->")
    lines += ["## Independent review", ""]
    if blocking:
        lines.append(f"**{len(blocking)} blocking finding(s)**: the merge gate stays red until a new push clears them.")
    else:
        lines.append("No blocking findings.")
    if summary:
        lines += ["", defuse(summary, 2000)]
    for title, group in (("Blocking", blocking), ("Advisory", advisory)):
        if not group:
            continue
        lines += ["", f"### {title}", ""]
        for f in group:
            where = defuse(f.get("file") or "", 300)
            if where and isinstance(f.get("line"), int):
                where += f":{f['line']}"
            lines.append(f"- **{defuse(f['title'], 300)}**" + (f" (`{where.replace('`', '')}`)" if where else ""))
            if f.get("detail"):
                lines.append("  " + defuse(f["detail"]).replace("\n", "\n  "))
    lines += ["", f"<sub>From a fresh session with read-only access to this pull request's code and main's AGENTS.md, "
                  f"run by .github/workflows/agent-review.yml ([run]({run_url})).</sub>"]
    text = "\n".join(lines)
    return text if len(text) <= MAX_COMMENT else text[:MAX_COMMENT] + "\n\n(cut short)"


LIMITS = {
    "error_max_turns": "The reviewer hit its turn limit (AGENT_REVIEW_MAX_TURNS) before answering; see the run",
    "error_max_budget_usd": "The reviewer hit its spending limit (AGENT_REVIEW_BUDGET_USD) before answering; see the run",
}


def usage(output: dict) -> None:
    turns, cost = output.get("num_turns"), output.get("total_cost_usd")
    if isinstance(turns, int) and isinstance(cost, (int, float)):
        print(f"The reviewer took {turns} turn(s) and about ${cost:.2f}.")


def report(path: str) -> dict:
    run_url = os.environ.get("RUN_URL", "")
    error = {"verdict": "error", "comment": ""}
    try:
        with open(path, encoding="utf-8") as f:
            output = json.load(f)
    except (OSError, ValueError):
        return {**error, "description": "The reviewer gave no readable output; see the run"}
    if not isinstance(output, dict):
        return {**error, "description": "The reviewer stopped with an error; see the run"}
    usage(output)
    if output.get("subtype") in LIMITS:
        return {**error, "description": LIMITS[output["subtype"]]}
    if output.get("is_error"):
        return {**error, "description": "The reviewer stopped with an error; see the run"}
    answer = structured(output)
    findings = findings_of(answer) if answer else None
    if findings is None:
        return {**error, "description": "The reviewer's answer wasn't in the expected form; see the run"}
    comment = render(findings, str(answer.get("summary") or ""), run_url,  # type: ignore[union-attr]
                     os.environ.get("REVIEWED_SHA", ""))
    raw = json.dumps(output)
    if any(key and key in raw for key in (os.environ.get(name, "") for name in SECRETS)):
        return {**error, "description": "The reviewer's answer contained a secret; not posted"}
    blocking = sum(f["severity"] == "blocking" for f in findings)
    if blocking:
        return {"verdict": "blocking", "description": f"{blocking} blocking finding(s); see the comment", "comment": comment}
    return {"verdict": "pass", "description": f"No blocking findings ({len(findings)} advisory)", "comment": comment}


def append_outputs(lines: list[str]) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def write_outputs(values: dict) -> None:
    append_outputs([f"verdict={values['verdict']}", f"description={values['description'][:140]}",
                    "comment=" + base64.b64encode(values["comment"].encode()).decode()])
    print(f"{values['verdict']}: {values['description']}")


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        messages = [json.loads(line) for line in sys.stdin if line.strip()]
        print("true" if is_agent(messages, os.environ.get("BODY", "")) else "false")
        return 0
    if len(argv) == 3 and argv[0] == "previous":
        with open(argv[1], encoding="utf-8") as f:
            bodies = [b for b in (json.loads(line) for line in f if line.strip()) if isinstance(b, str)]
        sha, verdict, text = previous(bodies)
        if sha:
            Path(argv[2]).write_text(text, encoding="utf-8")
            print(sha, verdict)
        return 0
    if argv == ["plan"]:
        values = plan(dict(os.environ))
        append_outputs([f"{k}={v}" for k, v in values.items()])
        print(", ".join(f"{k}: {v}" for k, v in values.items()))
        return 0
    if len(argv) == 2 and argv[0] == "report":
        write_outputs(report(argv[1]))
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
