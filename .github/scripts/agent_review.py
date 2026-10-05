"""The independent review's two decisions, for .github/workflows/agent-review.yml (run from main's copy, never a pull
request's). Standard library only.

  agent_review.py detect          Is this an agent's pull request? Reads its commit messages, one JSON string per line,
                                  on stdin, and its description in $BODY; prints true or false.
  agent_review.py report OUT.json Turns the reviewer's output (claude --output-format json, with --json-schema) into a
                                  verdict: writes verdict (pass, blocking or error), description and comment (the PR
                                  comment, base64) to $GITHUB_OUTPUT. A blocking finding, or output it can't read, fails
                                  the "Agent review" status, and with it the merge gate.

The reviewer read the pull request's code, so what it says is untrusted: the comment is built here, @mentions are
defused, and it is never interpolated into a command. A reply that contains $ANTHROPIC_API_KEY or
$CLAUDE_CODE_OAUTH_TOKEN is not posted."""
from __future__ import annotations

import base64
import json
import os
import re
import sys

MARKER = "<!-- agent-review -->"
SESSION = re.compile(r"^claude-session:\s*\S", re.IGNORECASE | re.MULTILINE)
CO_AUTHOR = re.compile(r"^co-authored-by:.*(\bclaude\b|anthropic\.com)", re.IGNORECASE | re.MULTILINE)
BODY_SIGNS = ("Generated with [Claude Code]", "claude.ai/code/session_")
SEVERITIES = ("blocking", "advisory")
MAX_COMMENT = 60000
SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")   # what the reviewer authenticates with (agent-review-run.sh)


def is_agent(messages: list[str], body: str) -> bool:
    if any(sign in body for sign in BODY_SIGNS):
        return True
    return any(SESSION.search(m) or CO_AUTHOR.search(m) for m in messages)


def structured(output: dict) -> dict | None:
    """The reviewer's answer: --json-schema's structured_output, else the reply itself as JSON (or its last ```json
    block)."""
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
    """Untrusted text, safe to put in a comment: no @mentions, no HTML comments (our marker), no runaway length."""
    s = str(text or "").replace("@", "@​").replace("<!--", "&lt;!--")
    return s if len(s) <= limit else s[:limit] + " …"


def render(findings: list[dict], summary: str, run_url: str) -> str:
    blocking = [f for f in findings if f["severity"] == "blocking"]
    advisory = [f for f in findings if f["severity"] == "advisory"]
    lines = [MARKER, "## Independent review", ""]
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


def report(path: str) -> dict:
    run_url = os.environ.get("RUN_URL", "")
    error = {"verdict": "error", "comment": ""}
    try:
        with open(path, encoding="utf-8") as f:
            output = json.load(f)
    except (OSError, ValueError):
        return {**error, "description": "The reviewer gave no readable output; see the run"}
    if not isinstance(output, dict) or output.get("is_error"):
        return {**error, "description": "The reviewer stopped with an error; see the run"}
    answer = structured(output)
    findings = findings_of(answer) if answer else None
    if findings is None:
        return {**error, "description": "The reviewer's answer wasn't in the expected form; see the run"}
    comment = render(findings, str(answer.get("summary") or ""), run_url)  # type: ignore[union-attr]
    raw = json.dumps(output)
    if any(key and key in raw for key in (os.environ.get(name, "") for name in SECRETS)):
        return {**error, "description": "The reviewer's answer contained a secret; not posted"}
    blocking = sum(f["severity"] == "blocking" for f in findings)
    if blocking:
        return {"verdict": "blocking", "description": f"{blocking} blocking finding(s); see the comment", "comment": comment}
    return {"verdict": "pass", "description": f"No blocking findings ({len(findings)} advisory)", "comment": comment}


def write_outputs(values: dict) -> None:
    lines = [f"verdict={values['verdict']}", f"description={values['description'][:140]}",
             "comment=" + base64.b64encode(values["comment"].encode()).decode()]
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"{values['verdict']}: {values['description']}")


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        messages = [json.loads(line) for line in sys.stdin if line.strip()]
        print("true" if is_agent(messages, os.environ.get("BODY", "")) else "false")
        return 0
    if len(argv) == 2 and argv[0] == "report":
        write_outputs(report(argv[1]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
