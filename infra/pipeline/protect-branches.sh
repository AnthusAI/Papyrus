#!/usr/bin/env bash
# Create (or bring back to the intended settings) the repository ruleset that keeps red changes off main and develop.
#
#   infra/pipeline/protect-branches.sh [--repo OWNER/REPO] [--dry-run]
#
# It asks no person for anything at merge time. The rules are all automatic:
#   - main and develop take changes only through a pull request (no required reviewers, zero approvals)
#   - the checks `ts` and `python` of tests.yml must have passed on the pull request's tip (a skipped check, which is how a reused green run
#     reports, passes; a pull request that changes only the board is covered by tests-board-only.yml)
#   - no force-push, no deletion
#   - nobody bypasses it: release.yml's back-merge of main into develop is a pull request from a back-merge/vX branch, tests dispatched on it, auto-merge on.
#     That needs the repository settings "Allow GitHub Actions to create pull requests" and "Allow auto-merge" (both set by the person who runs this script).
# The release workflow runs the same tests before it publishes (release.yml, job `tests`), so a direct push that slips past still publishes nothing red.
# Needs admin rights on the repository and the gh CLI (gh auth login). Safe to run again: it updates the ruleset of the same name.
set -u

REPO="AnthusAI/Papyrus"
RULESET_NAME="main-and-develop-need-green-tests"
DRY_RUN=0

refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) refuse "unknown argument $1 (see --help)" ;;
  esac
done
case "$REPO" in */*) ;; *) refuse "--repo must be OWNER/REPO" ;; esac
command -v gh >/dev/null 2>&1 || refuse "the gh CLI is needed (https://cli.github.com), then gh auth login"

BODY="$(cat <<JSON
{
  "name": "$RULESET_NAME",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main", "refs/heads/develop"], "exclude": []}},
  "bypass_actors": [],
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "dismiss_stale_reviews_on_push": false, "require_code_owner_review": false, "require_last_push_approval": false, "required_review_thread_resolution": false}},
    {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": false, "required_status_checks": [{"context": "ts"}, {"context": "python"}]}}
  ]
}
JSON
)"

if [ "$DRY_RUN" = 1 ]; then printf '%s\n' "$BODY"; exit 0; fi

echo "1. Looking for an existing ruleset named $RULESET_NAME on $REPO"
EXISTING_ID="$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$RULESET_NAME\") | .id" 2>/dev/null)" || fail "could not list rulesets (admin rights on $REPO are needed)"

if [ -n "$EXISTING_ID" ]; then
  echo "2. Updating ruleset $EXISTING_ID"
  printf '%s' "$BODY" | gh api --method PUT "repos/$REPO/rulesets/$EXISTING_ID" --input - >/dev/null || fail "could not update the ruleset"
else
  echo "2. Creating the ruleset"
  printf '%s' "$BODY" | gh api --method POST "repos/$REPO/rulesets" --input - >/dev/null || fail "could not create the ruleset"
fi

echo "3. Reading it back"
gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$RULESET_NAME\") | {id, enforcement, target}" || fail "could not read the ruleset back"
echo "Done. main and develop now need a pull request with green ts and python checks; nobody has to click anything."
