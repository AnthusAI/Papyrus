#!/usr/bin/env bash
# Human-run proof for a site's GitHub OIDC CI role (not run in CI).
#
# Run inside a throwaway GitHub Actions job in the site's repository, on a
# listed branch, AFTER aws-actions/configure-aws-credentials@v4 assumed the
# role (see docs/site-hosting.md, "CI access without keys"):
#
#   scripts/verify-oidc-role.sh <role-arn> <amplify-app-id> [branch-name]
#
# Allowed:  sts get-caller-identity returns the assumed role, and
#           amplify list-jobs on the site's app succeeds.
# Denied:   iam list-users fails with AccessDenied.
# Separately (by hand): the same workflow on a branch NOT in github.branches
# must fail at the assume-role step.
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 <role-arn> <amplify-app-id> [branch-name]" >&2
  exit 2
fi

role_arn="$1"
app_id="$2"
branch_name="${3:-main}"
role_name="${role_arn##*/}"

caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
case "$caller_arn" in
  arn:aws:sts::*:assumed-role/"$role_name"/*) echo "ok: running as $caller_arn" ;;
  *) echo "FAIL: caller is $caller_arn, expected an assumed session of $role_arn" >&2; exit 1 ;;
esac

aws amplify list-jobs --app-id "$app_id" --branch-name "$branch_name" --max-results 1 >/dev/null
echo "ok: amplify list-jobs allowed for app $app_id branch $branch_name"

denied_output="$(aws iam list-users 2>&1 || true)"
case "$denied_output" in
  *AccessDenied*) echo "ok: iam list-users denied" ;;
  *) echo "FAIL: iam list-users was not denied: $denied_output" >&2; exit 1 ;;
esac

echo "role $role_arn behaves as least privilege"
