"""Remove findings that carry an inline `nosemgrep` from a SARIF file.

Semgrep keeps them in its SARIF output, marked as suppressed, and code scanning still raises an alert for each one.
"""
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    sarif = json.load(f)
dropped = 0
for run in sarif.get("runs", []):
    results = run.get("results", [])
    kept = [r for r in results if not r.get("suppressions")]
    dropped += len(results) - len(kept)
    run["results"] = kept
with open(path, "w", encoding="utf-8") as f:
    json.dump(sarif, f)
print(f"dropped {dropped} findings suppressed in source")
