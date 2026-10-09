#!/usr/bin/env bash
# The merge gate: one commit status ("Merge gate") on a pull request's head that says whether it's ready to merge, so a
# ruleset on main can require that one check instead of a list that goes stale. Run by .github/workflows/merge-gate.yml
# each time a pull request's workflows finish, from main's copy (it never runs a pull request's code).
#
# It passes when, on the pull request's head commit:
#   - the newest run of every workflow started by the pull request succeeded (or was skipped), and the ones in
#     REQUIRED_WORKFLOWS ran at all. CodeQL counts as one of them: GitHub's default setup runs it as a "dynamic" workflow
#     (not a pull_request one), under the name "PR #<n>";
#   - every other app's check run (CodeQL, Semgrep, Trivy, zizmor, ...) succeeded, and every commit status did, and the
#     ones in REQUIRED_STATUSES were set at all: "Agent review" (.github/workflows/agent-review.yml) is the independent
#     review, which fails on an agent's pull request with a blocking finding and passes on anyone else's. It must be on
#     the head commit itself: when the review copies a passing verdict forward (a push that only merged main in), it
#     sets the status on the new head, and a head without one waits.
# Anything still running makes it "pending". Workflows and apps that aren't about whether the change is sound are left
# out (IGNORED_*). When it passes on one of Dependabot's pull requests, it merges it (see the end).
#
# CodeQL's finishing starts no workflow here (GitHub sends no event for its own Actions runs), so when CodeQL is all
# it's waiting for, it looks again every POLL_SECONDS, up to POLL_ATTEMPTS times, rather than stay pending.
#
# Needs: GH_TOKEN, REPO (owner/name), and SHA (the head commit) or PR (a number). RUN_URL links the status to the run.
# DRY_RUN=1 prints what it would do instead of doing it.
set -euo pipefail

CONTEXT="Merge gate"
REQUIRED_WORKFLOWS=("Docker image" "Security scans" "CodeQL")   # take CodeQL out if its default setup is turned off
REQUIRED_STATUSES=("Agent review")   # Dependabot's pull requests aren't reviewed (below)
IGNORED_WORKFLOWS='^(Cancel runs on close|Merge gate)$'
IGNORED_APPS='^(codecov|github-actions)$'   # Codecov's statuses are informational; Actions' runs are counted above
IGNORED_STATUSES="^(${CONTEXT}|codecov/.*)$"
OK_CONCLUSIONS='^(success|skipped|neutral)$'
POLLED='^CodeQL( \(not started\))?$'
POLL_SECONDS=${POLL_SECONDS:-30}
POLL_ATTEMPTS=${POLL_ATTEMPTS:-20}

run() { if [ "${DRY_RUN:-}" = 1 ]; then echo "(dry run) $*"; else "$@"; fi; }

if [ -n "${PR:-}" ]; then
  SHA=$(gh api "repos/$REPO/pulls/$PR" --jq .head.sha)
fi
[[ "${SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::No head commit to check (SHA=${SHA:-})."; exit 1; }

# The open pull request whose head is this commit (none: it was merged, closed, or pushed to since). The status is
# the commit's, so two pull requests sharing a head (a fork reusing another's commit) can't each be judged: neither is.
prs=$(gh api --paginate "repos/$REPO/pulls?state=open&base=main&per_page=100" \
        --jq ".[] | select(.head.sha == \"$SHA\") | [.number, .user.login, .head.repo.full_name, .draft] | @tsv")
if [ -z "$prs" ]; then echo "No open pull request into main at $SHA."; exit 0; fi
if [ "$(wc -l <<< "$prs")" -gt 1 ]; then
  echo "::error::More than one open pull request has $SHA as its head; not deciding for any of them."
  run gh api -X POST "repos/$REPO/statuses/$SHA" -f state=failure -f context="$CONTEXT" \
    -f description="More than one open pull request has this commit as its head" ${RUN_URL:+-f target_url="$RUN_URL"} >/dev/null
  exit 1
fi
IFS=$'\t' read -r number author head_repo draft <<< "$prs"
echo "Pull request #$number by $author at $SHA"
# CodeQL's default setup doesn't analyse Dependabot's pull requests (its check says the configurations "were not found"),
# so none of its runs ever comes: waiting for one would keep the gate pending, and the merge below, forever. A run that
# does come still counts, as for any workflow; the tests and the security scans are still required. Nor does the agent
# review run on them (no agent wrote them), so its status isn't asked for either.
if [ "$author" = "dependabot[bot]" ]; then
  required=(); for w in "${REQUIRED_WORKFLOWS[@]}"; do [ "$w" = CodeQL ] || required+=("$w"); done
  REQUIRED_WORKFLOWS=("${required[@]}")
  REQUIRED_STATUSES=()
fi

list() { local out="" x; for x in "$@"; do out+="${out:+, }$x"; done; echo "$out"; }

evaluate() {
  failing=() pending=() seen=()

  # 1. The workflows the pull request started: the newest run of each (a re-run or a reopen starts another).
  runs=$(gh api --paginate "repos/$REPO/actions/runs?head_sha=$SHA&per_page=100" --jq '.workflow_runs[]
           | select(.event == "pull_request" or (.event == "dynamic" and ((.path // "") | startswith("dynamic/github-code-scanning/"))))
           | [.created_at, .workflow_id, (if .event == "dynamic" then "CodeQL" else .name end), .status, (.conclusion // "")] | @tsv')
  latest=$(sort <<< "$runs" | awk -F'\t' 'NF { last[$2] = $0 } END { for (k in last) print last[k] }')
  while IFS=$'\t' read -r _ _ name status conclusion; do
    [ -n "${name:-}" ] || continue
    [[ "$name" =~ $IGNORED_WORKFLOWS ]] && continue
    seen+=("$name")
    if [ "$status" != completed ]; then pending+=("$name")
    elif ! [[ "$conclusion" =~ $OK_CONCLUSIONS ]]; then failing+=("$name ($conclusion)"); fi
  done <<< "$latest"
  for w in "${REQUIRED_WORKFLOWS[@]}"; do
    printf '%s\n' "${seen[@]:-}" | grep -qxF "$w" || pending+=("$w (not started)")
  done

  # 2. Other apps' check runs.
  checks=$(gh api --paginate "repos/$REPO/commits/$SHA/check-runs?per_page=100" \
             --jq '.check_runs[] | [.app.slug, .name, .status, (.conclusion // "")] | @tsv')
  while IFS=$'\t' read -r app name status conclusion; do
    [ -n "${app:-}" ] || continue
    [[ "$app" =~ $IGNORED_APPS ]] && continue
    if [ "$status" != completed ]; then pending+=("$name")
    elif ! [[ "$conclusion" =~ $OK_CONCLUSIONS ]]; then failing+=("$name ($conclusion)"); fi
  done <<< "$checks"

  # 3. Commit statuses: the newest of each context (the API lists newest first).
  statuses=$(gh api --paginate "repos/$REPO/commits/$SHA/statuses?per_page=100" --jq '.[] | [.context, .state] | @tsv')
  newest=$(awk -F'\t' 'NF && !seen[$1]++' <<< "$statuses")
  for s in "${REQUIRED_STATUSES[@]}"; do
    grep -qxF "$s" <<< "$(cut -f1 <<< "$newest")" || pending+=("$s (not started)")
  done
  while IFS=$'\t' read -r context result; do
    [ -n "${context:-}" ] || continue
    [[ "$context" =~ $IGNORED_STATUSES ]] && continue
    case "$result" in
      success) ;;
      pending) pending+=("$context") ;;
      *) failing+=("$context ($result)") ;;
    esac
  done <<< "$newest"

  if [ ${#failing[@]} -gt 0 ]; then
    state=failure; description="Failed: $(list "${failing[@]}")"
  elif [ ${#pending[@]} -gt 0 ]; then
    state=pending; description="Waiting for: $(list "${pending[@]}")"
  else
    state=success; description="Every check passed"
  fi
}

# Only CodeQL still to come: look again shortly rather than wait for an event that won't come.
only_codeql() { local x; for x in "${pending[@]}"; do [[ "$x" =~ $POLLED ]] || return 1; done; }
posted=""
for (( attempt = 0; ; attempt++ )); do
  evaluate
  echo "$state: $description"
  if [ "$state:$description" != "$posted" ]; then
    run gh api -X POST "repos/$REPO/statuses/$SHA" -f state="$state" -f context="$CONTEXT" \
      -f description="${description:0:140}" ${RUN_URL:+-f target_url="$RUN_URL"} >/dev/null
    posted="$state:$description"
  fi
  [ "$state" = pending ] && [ ${#failing[@]} -eq 0 ] && only_codeql && [ "$attempt" -lt "$POLL_ATTEMPTS" ] || break
  sleep "$POLL_SECONDS"
done

# Dependabot's pull requests merge themselves once the gate passes (any update type: the gate is the tests), as long as
# every commit is Dependabot's own, so nobody else's change rides along.
[ "$state" = success ] && [ "$author" = "dependabot[bot]" ] && [ "$head_repo" = "$REPO" ] && [ "$draft" = false ] || exit 0
others=$(gh api --paginate "repos/$REPO/pulls/$number/commits" \
           --jq '.[] | select(.author.login != "dependabot[bot]" or .commit.verification.verified != true) | .sha')
if [ -n "$others" ]; then echo "::notice::#$number has commits from someone other than Dependabot; leaving it for review."; exit 0; fi
# --match-head-commit refuses if the pull request moved on since the checked commit.
run gh pr merge "$number" --repo "$REPO" --squash --match-head-commit "$SHA"
# A merge made with this token starts no workflows by itself: start main's release build and security scan.
run gh workflow run docker.yml --repo "$REPO" --ref main
run gh workflow run security.yml --repo "$REPO" --ref main
