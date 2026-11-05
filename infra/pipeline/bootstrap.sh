#!/usr/bin/env bash
# Set up, or bring up to date, the roles the release pipeline deploys with (PPY-b8cc79, PPY-9d1b3e).
#
# A PERSON runs this, with credentials that can create IAM roles in the target account. Agents must not run it unless told to.
# It is safe to run again and again: with nothing to change it says so and touches nothing.
#
#   infra/pipeline/bootstrap.sh --account <12-digit account id> [--create-oidc-provider] [--repo OWNER/REPO] [--plan-only] [--yes]
#
# What it does, in order, saying each step:
#   0. fetches, and refuses unless papyrus-stack-pipeline.yaml in this checkout equals the one on origin/develop or origin/main (no
#      override: an urgent change goes through a merge to develop first). With --plan-only it warns instead, to preview a pull request.
#   1. checks the AWS credentials belong to --account (the id is never stored in Git; you type it, so you mean it)
#   2. checks the account's GitHub OIDC provider: exists, or is created by this stack when you pass --create-oidc-provider
#   3. creates a change set for the papyrus-stack-pipeline stack and shows it; asks before executing (--yes skips the question)
#   4. sets the AWS_ACCOUNT_ID repository variable (so the workflows can find the roles)
#   5. verifies: the three roles exist and the deployed template equals infra/pipeline/papyrus-stack-pipeline.yaml
# Run it again after ANY change to infra/pipeline/papyrus-stack-pipeline.yaml.
#
# Exit codes: 0 done (or already up to date), 1 something failed, 2 refused (wrong account, missing prerequisite, stack in a bad state).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$HERE/papyrus-stack-pipeline.yaml"
STACK="papyrus-stack-pipeline"
REGION="${AWS_REGION:-us-east-1}"
REPO="AnthusAI/Papyrus"
ACCOUNT=""
CREATE_PROVIDER=""
PLAN_ONLY=""
YES=""

say() { printf '%s\n' "$*"; }
refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --account) ACCOUNT="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --create-oidc-provider) CREATE_PROVIDER="true"; shift ;;
    --plan-only) PLAN_ONLY="true"; shift ;;
    --yes) YES="true"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) refuse "unknown argument $1 (see --help)" ;;
  esac
done

case "$ACCOUNT" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) refuse "pass --account <12-digit AWS account id>. Say which account you mean; the id is not kept in Git." ;;
esac
case "$REPO" in
  */*) ;;
  *) refuse "--repo must be OWNER/REPO" ;;
esac

say "0. Template source"
TEMPLATE_PATH="infra/pipeline/papyrus-stack-pipeline.yaml"
git -C "$HERE" fetch -q origin develop main || fail "could not fetch origin develop and main (needed to check the template is merged)"
MATCHED=""
for BRANCH in develop main; do
  if [ -z "$MATCHED" ] && git -C "$HERE" show "origin/$BRANCH:$TEMPLATE_PATH" 2>/dev/null | cmp -s - "$TEMPLATE"; then
    MATCHED="origin/$BRANCH"
  fi
done
if [ -n "$MATCHED" ]; then
  say "   the template matches $MATCHED"
elif [ -n "$PLAN_ONLY" ]; then
  say "   WARNING: the template differs from origin/develop and origin/main (an unmerged change). --plan-only shows it; applying would be refused."
else
  refuse "$TEMPLATE_PATH in this checkout matches neither origin/develop nor origin/main, so it is not merged. Roles are applied only from merged templates. Merge the change to develop, check out an up-to-date develop, and run this again. To preview an unmerged change, add --plan-only."
fi

export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"

say "1. Account"
ACTUAL="$(aws sts get-caller-identity --query Account --output text)" || fail "cannot read the AWS identity (log in first, for example aws sso login)"
if [ "$ACTUAL" != "$ACCOUNT" ]; then
  refuse "the credentials in use belong to account $ACTUAL, not $ACCOUNT. Nothing was changed. Check AWS_PROFILE."
fi
say "   credentials belong to account $ACCOUNT, region $REGION"

say "2. GitHub OIDC provider"
PROVIDER_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
PROVIDERS="$(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text)" || fail "cannot list OIDC providers"
STATE="$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || true)"
case "$STATE" in
  ""|None) STATE="" ;;
esac
# An account whose provider this stack created must keep creating it, or the next run would delete it.
OWNS="$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Parameters[?ParameterKey==`CreateGitHubOidcProvider`].ParameterValue | [0]' --output text 2>/dev/null || true)"
if [ "$OWNS" = "true" ]; then
  CREATE_PROVIDER="true"
fi
case " $PROVIDERS " in
  *"$PROVIDER_ARN"*) PROVIDER_EXISTS="true" ;;
  *) PROVIDER_EXISTS="" ;;
esac
if [ "$CREATE_PROVIDER" = "true" ]; then
  if [ -n "$PROVIDER_EXISTS" ] && [ "$OWNS" != "true" ]; then
    refuse "this account already has a GitHub OIDC provider that this stack did not create, and an account can hold only one. Run again without --create-oidc-provider."
  fi
  say "   this stack creates and owns the provider (CreateGitHubOidcProvider=true)"
elif [ -n "$PROVIDER_EXISTS" ]; then
  say "   found the account's provider; this stack only references it"
else
  refuse "this account has no GitHub OIDC provider (token.actions.githubusercontent.com). Run again with --create-oidc-provider to have this stack create it."
fi
PROVIDER_VALUE="false"
[ "$CREATE_PROVIDER" = "true" ] && PROVIDER_VALUE="true"

say "3. Change set for the $STACK stack"
case "$STATE" in
  "") KIND="CREATE" ;;
  CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE) KIND="UPDATE" ;;
  REVIEW_IN_PROGRESS) KIND="CREATE" ;;
  *) refuse "the $STACK stack is $STATE; a person must repair it before this can run." ;;
esac
CHANGE_SET="bootstrap-$(date -u +%Y%m%d%H%M%S)"
aws cloudformation create-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --change-set-type "$KIND" \
  --template-body "file://$TEMPLATE" --capabilities CAPABILITY_NAMED_IAM \
  --parameters "ParameterKey=GitHubRepository,ParameterValue=$REPO" "ParameterKey=CreateGitHubOidcProvider,ParameterValue=$PROVIDER_VALUE" \
  >/dev/null || fail "could not create the change set"
aws cloudformation wait change-set-create-complete --stack-name "$STACK" --change-set-name "$CHANGE_SET" 2>/dev/null
CS_STATUS="$(aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --query 'Status' --output text)"
CS_REASON="$(aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --query 'StatusReason' --output text)"
CHANGED=""
if [ "$CS_STATUS" = "FAILED" ]; then
  case "$CS_REASON" in
    *"didn't contain changes"*|*"No updates are to be performed"*)
      say "   no changes: the roles in the account already match this template"
      aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
      ;;
    *) fail "the change set could not be created: $CS_REASON" ;;
  esac
else
  CHANGED="true"
  say "   the change set would make these changes:"
  aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" \
    --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table
  if [ -n "$PLAN_ONLY" ]; then
    aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
    say "   --plan-only: change set deleted, nothing applied."
    exit 0
  fi
  if [ -z "$YES" ]; then
    printf '   Apply these changes to account %s? Type yes: ' "$ACCOUNT"
    read -r ANSWER
    if [ "$ANSWER" != "yes" ]; then
      aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
      refuse "not confirmed; change set deleted, nothing applied."
    fi
  fi
  aws cloudformation execute-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" || fail "could not execute the change set"
  say "   executing; waiting for the stack to finish"
  if [ "$KIND" = "CREATE" ]; then
    aws cloudformation wait stack-create-complete --stack-name "$STACK" || fail "the stack did not finish creating; read its events"
  else
    aws cloudformation wait stack-update-complete --stack-name "$STACK" || fail "the stack did not finish updating; read its events"
  fi
  say "   applied"
fi

say "4. Repository variable AWS_ACCOUNT_ID on $REPO"
if command -v gh >/dev/null 2>&1; then
  CURRENT="$(gh variable get AWS_ACCOUNT_ID --repo "$REPO" 2>/dev/null || true)"
  if [ "$CURRENT" = "$ACCOUNT" ]; then
    say "   already set to this account"
  else
    gh variable set AWS_ACCOUNT_ID --repo "$REPO" --body "$ACCOUNT" || fail "could not set the variable; set AWS_ACCOUNT_ID on $REPO to $ACCOUNT by hand (Settings, Secrets and variables, Actions, Variables)"
    say "   set (it was ${CURRENT:-unset})"
  fi
else
  say "   gh is not installed: set the repository variable AWS_ACCOUNT_ID on $REPO to $ACCOUNT by hand (Settings, Secrets and variables, Actions, Variables)"
fi

say "5. Verify"
for ROLE in papyrus-stack-plan-github papyrus-stack-deploy-github papyrus-stack-deploy-cloudformation; do
  aws iam get-role --role-name "$ROLE" --query 'Role.RoleName' --output text >/dev/null || fail "role $ROLE does not exist"
  say "   role $ROLE exists"
done
if AWS_ACCOUNT_ID="$ACCOUNT" python3 "$HERE/stack_deploy.py" pipeline-check; then
  :
else
  fail "the deployed template does not match infra/pipeline/papyrus-stack-pipeline.yaml (see the line above)"
fi
if [ -n "$CHANGED" ]; then
  say "Done: the pipeline roles were updated."
else
  say "Done: nothing needed changing."
fi
say "Still needed on a NEW account (this script does not do them): see infra/pipeline/README.md, 'A new account, in order'."
exit 0
