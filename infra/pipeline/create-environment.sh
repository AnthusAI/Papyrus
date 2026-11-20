#!/usr/bin/env bash
# Create (or bring back to the intended settings) the GitHub environment `pipeline-roles` that the apply role trusts (PPY-9d1b3e).
#
#   infra/pipeline/create-environment.sh [--repo OWNER/REPO] [--environment NAME]
#
# A PERSON with admin rights on the repository runs this once. Agents must not run it unless told to. Safe to run again.
# It uses the gh CLI (gh auth login first) and changes only this environment:
#   - no required reviewer: the automatic check in role_stack.py plan is the control, and nobody clicks anything (a reviewer set earlier is removed)
#   - deployment branches: develop and main only (the role-stack-deploy workflow's `apply` job cannot run from any other branch)
#   - a person who triggered the run may approve it (prevent_self_review is off), so a one-person team is not locked out
# The environment name is also the OIDC subject the AWS apply role trusts, exactly: repo:<owner>/<repo>:environment:<name>.
set -u

REPO="AnthusAI/Papyrus"
ENVIRONMENT="pipeline-roles"

refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) refuse "unknown argument $1 (see --help; there is no --reviewer any more: the automatic check replaced the approval click)" ;;
  esac
done
case "$REPO" in */*) ;; *) refuse "--repo must be OWNER/REPO" ;; esac
command -v gh >/dev/null 2>&1 || refuse "the gh CLI is needed (https://cli.github.com), then gh auth login"

echo "1. Creating or updating the environment $ENVIRONMENT on $REPO with no required reviewer"
printf '{"reviewers":[],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true},"prevent_self_review":false}' \
  | gh api --method PUT "repos/$REPO/environments/$ENVIRONMENT" --input - >/dev/null || fail "could not create the environment (admin rights on $REPO are needed)"

echo "2. Limiting deployment branches to develop and main"
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
echo "Done. Role changes merged to develop or main apply automatically after the plan's check; nobody is asked to approve."
