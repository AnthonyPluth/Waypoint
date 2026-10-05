#!/usr/bin/env bash
set -eo pipefail
# Only the newest commit on main moves :latest (and :1.2, :1); re-running an older build doesn't.
git fetch --quiet origin main
head=$(git rev-parse FETCH_HEAD)
newest=false
if [ "$head" = "$GITHUB_SHA" ]; then newest=true; fi
echo "newest=$newest" >> "$GITHUB_OUTPUT"
# Re-running a build for a commit that's already tagged reuses its version.
existing=$(git tag --points-at HEAD --list 'v[0-9]*.[0-9]*.[0-9]*' | sort -V | tail -1)
if [ -n "$existing" ]; then
  echo "version=$existing" >> "$GITHUB_OUTPUT"; echo "new=false" >> "$GITHUB_OUTPUT"
  echo "Already tagged $existing"; exit 0
fi
if [ "$newest" != true ]; then
  echo "::notice::$GITHUB_SHA isn't the newest commit on main any more, so it isn't released."
  echo "skip=true" >> "$GITHUB_OUTPUT"; exit 0
fi
# How big a step this is comes from the commits since the last version released from this commit's own
# history. Where it steps from is the highest version ever tagged, so versions only go up, even when main's
# history is rewritten and its older tags aren't in it (after the rewrite of 2026-09-30, this step went back
# from v2.3.21 to v1.0.2).
last=$(git describe --tags --abbrev=0 --first-parent --match 'v[0-9]*.[0-9]*.[0-9]*' HEAD 2>/dev/null || true)
highest=$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' | sort -V | tail -1)
if [ -z "$highest" ]; then
  next=v1.0.0
else
  if [ -n "$last" ]; then log=$(git log --format='%s%n%b' "$last"..HEAD); else log=$(git log --format='%s%n%b' HEAD); fi
  IFS=. read -r major minor patch <<< "${highest#v}"
  # Pull request titles say what a change is (they're in each merge commit's message): "feat: ..." is a
  # new feature (a minor version), "fix: ..." or anything else a patch, and a "!" before the colon
  # ("feat!: ...") something that breaks an existing setup (a major version).
  # A marker counts only where a line starts with it (or ends with #major / #minor), so a commit message
  # that merely talks about them (like this comment) doesn't release a version.
  if grep -qE '(^|[[:space:]])#major[[:space:]]*$|^BREAKING CHANGE:|^[a-z]+(\(.*\))?!:' <<< "$log"; then
    next="v$((major + 1)).0.0"
  elif grep -qE '(^|[[:space:]])#minor[[:space:]]*$|^feat(\(.*\))?:' <<< "$log"; then
    next="v${major}.$((minor + 1)).0"
  else
    next="v${major}.${minor}.$((patch + 1))"
  fi
fi
# Never reuse a version that's already tagged elsewhere (say, by an older release from another branch).
while git rev-parse -q --verify "refs/tags/$next" >/dev/null; do
  IFS=. read -r major minor patch <<< "${next#v}"; next="v${major}.${minor}.$((patch + 1))"
done
echo "version=$next" >> "$GITHUB_OUTPUT"; echo "new=true" >> "$GITHUB_OUTPUT"
echo "Next version: $next (last in this history: ${last:-none}; highest: ${highest:-none})"
