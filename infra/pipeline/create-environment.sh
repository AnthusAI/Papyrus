#!/usr/bin/env bash
# Create (or bring back to the intended settings) the GitHub environment `pipeline-roles` that gates role changes (PPY-9d1b3e).
#
#   infra/pipeline/create-environment.sh --reviewer <github login> [--repo OWNER/REPO] [--environment NAME]
#
# A PERSON with admin rights on the repository runs this once. Agents must not run it unless told to. Safe to run again.
# It uses the gh CLI (gh auth login first) and changes only this environment:
#   - required reviewer: the login you pass (the one-click approval for pipeline role changes)
#   - deployment branches: develop and main only (the role-stack-deploy workflow's `apply` job cannot run from any other branch)
#   - a person who triggered the run may approve it (prevent_self_review is off), so a one-person team is not locked out
# The environment name is also the OIDC subject the AWS apply role trusts, exactly: repo:<owner>/<repo>:environment:<name>.
set -u

REPO="AnthusAI/Papyrus"
ENVIRONMENT="pipeline-roles"
REVIEWER=""

refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --reviewer) REVIEWER="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) refuse "unknown argument $1 (see --help)" ;;
  esac
done
[ -n "$REVIEWER" ] || refuse "pass --reviewer <github login>: the person who approves pipeline role changes"
case "$REPO" in */*) ;; *) refuse "--repo must be OWNER/REPO" ;; esac
command -v gh >/dev/null 2>&1 || refuse "the gh CLI is needed (https://cli.github.com), then gh auth login"

echo "1. Looking up the reviewer $REVIEWER"
REVIEWER_ID="$(gh api "users/$REVIEWER" --jq .id)" || fail "no GitHub user $REVIEWER"
case "$REVIEWER_ID" in
  ''|*[!0-9]*) fail "unexpected id for $REVIEWER" ;;
esac

echo "2. Creating or updating the environment $ENVIRONMENT on $REPO"
printf '{"reviewers":[{"type":"User","id":%s}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true},"prevent_self_review":false}' "$REVIEWER_ID" \
  | gh api --method PUT "repos/$REPO/environments/$ENVIRONMENT" --input - >/dev/null || fail "could not create the environment (admin rights on $REPO are needed)"

echo "3. Limiting deployment branches to develop and main"
EXISTING="$(gh api "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" --jq '.branch_policies[].name' 2>/dev/null || true)"
for BRANCH in develop main; do
  case "
$EXISTING
" in
    *"
$BRANCH
"*) echo "   $BRANCH already allowed" ;;
    *)
      printf '{"name":"%s","type":"branch"}' "$BRANCH" \
        | gh api --method POST "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" --input - >/dev/null || fail "could not allow branch $BRANCH"
      echo "   $BRANCH allowed"
      ;;
  esac
done
echo "Done. Role changes merged to develop or main now wait for $REVIEWER to approve the '$ENVIRONMENT' deployment in GitHub."
