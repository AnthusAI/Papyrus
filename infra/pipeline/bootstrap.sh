#!/usr/bin/env bash
# NOTE: for a deployment account that is not an Anthus account, do not use this script (its default repository is Papyrus and it writes that
# repository's AWS_ACCOUNT_ID variable). Use the account baseline instead: docs/account-pipeline.md (epic PPY-9bd776).
#
# One-time setup of the approval-gated role deploy on an AWS account, and the emergency path for the pipeline roles (PPY-9d1b3e).
#
# NORMAL PATH (nobody runs anything): a change to infra/pipeline/papyrus-stack-pipeline.yaml is merged, the role-stack-deploy workflow
# plans it, and the reviewer approves in GitHub. This script is for what that workflow cannot do for itself:
#
#   infra/pipeline/bootstrap.sh --account <12-digit account id> --approver-only [--create-oidc-provider]
#       the ONCE-PER-ACCOUNT setup. Applies the small papyrus-pipeline-approver stack (the roles the workflow runs as, and optionally the
#       account's GitHub OIDC provider) and sets the AWS_ACCOUNT_ID repository variable. Re-run it only when
#       infra/pipeline/papyrus-pipeline-approver.yaml changes. After it, run infra/pipeline/create-environment.sh once.
#
#   infra/pipeline/bootstrap.sh --account <12-digit account id>
#       the EMERGENCY path (the workflow is unavailable): the same, and then the papyrus-stack-pipeline stack too.
#
# A PERSON runs this with credentials that can create IAM roles in the account. Agents must not run it unless told to.
# Safe to run again and again: with nothing to change it says so and touches nothing. Other flags: --repo OWNER/REPO, --plan-only, --yes.
#
# What it does, in order, saying each step:
#   0. fetches, and refuses unless each template in this checkout equals the one on origin/develop or origin/main (no override: an
#      urgent change goes through a merge to develop first). With --plan-only it warns instead, to preview a pull request.
#   1. checks the AWS credentials belong to --account (the id is never stored in Git; you type it, so you mean it)
#   2. checks the account's GitHub OIDC provider: exists, or is created by the approver stack when you pass --create-oidc-provider
#   3. creates a change set for each stack and shows it; asks before executing (--yes skips the question)
#   4. sets the AWS_ACCOUNT_ID repository variable (so the workflows can find the roles)
#   5. verifies the roles exist (and, on the emergency path, that the deployed template equals the repository)
#
# Exit codes: 0 done (or already up to date), 1 something failed, 2 refused (wrong account, unmerged template, missing prerequisite).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
APPROVER_TEMPLATE="$HERE/papyrus-pipeline-approver.yaml"
PIPELINE_TEMPLATE="$HERE/papyrus-stack-pipeline.yaml"
APPROVER_STACK="papyrus-pipeline-approver"
PIPELINE_STACK="papyrus-stack-pipeline"
REGION="${AWS_REGION:-us-east-1}"
REPO="AnthusAI/Papyrus"
ACCOUNT=""
CREATE_PROVIDER=""
PLAN_ONLY=""
YES=""
APPROVER_ONLY=""
CHANGED=""

say() { printf '%s\n' "$*"; }
refuse() { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --account) ACCOUNT="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --create-oidc-provider) CREATE_PROVIDER="true"; shift ;;
    --approver-only) APPROVER_ONLY="true"; shift ;;
    --plan-only) PLAN_ONLY="true"; shift ;;
    --yes) YES="true"; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
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
git -C "$HERE" fetch -q origin develop main || fail "could not fetch origin develop and main (needed to check the templates are merged)"
for TEMPLATE_PATH in infra/pipeline/papyrus-pipeline-approver.yaml infra/pipeline/papyrus-stack-pipeline.yaml; do
  MATCHED=""
  for BRANCH in develop main; do
    if [ -z "$MATCHED" ] && git -C "$HERE" show "origin/$BRANCH:$TEMPLATE_PATH" 2>/dev/null | cmp -s - "$HERE/../../$TEMPLATE_PATH"; then
      MATCHED="origin/$BRANCH"
    fi
  done
  if [ -n "$MATCHED" ]; then
    say "   $TEMPLATE_PATH matches $MATCHED"
  elif [ -n "$PLAN_ONLY" ]; then
    say "   WARNING: $TEMPLATE_PATH differs from origin/develop and origin/main (an unmerged change). --plan-only shows it; applying would be refused."
  else
    refuse "$TEMPLATE_PATH in this checkout matches neither origin/develop nor origin/main, so it is not merged. Roles are applied only from merged templates. Merge the change to develop, check out an up-to-date develop, and run this again. To preview an unmerged change, add --plan-only."
  fi
done

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
# An account whose provider the approver stack created must keep creating it, or the next run would delete it.
OWNS="$(aws cloudformation describe-stacks --stack-name "$APPROVER_STACK" --query 'Stacks[0].Parameters[?ParameterKey==`CreateGitHubOidcProvider`].ParameterValue | [0]' --output text 2>/dev/null || true)"
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
  say "   the approver stack creates and owns the provider (CreateGitHubOidcProvider=true)"
elif [ -n "$PROVIDER_EXISTS" ]; then
  say "   found the account's provider; the stacks only reference it"
else
  refuse "this account has no GitHub OIDC provider (token.actions.githubusercontent.com). Run again with --create-oidc-provider to have the approver stack create it."
fi
PROVIDER_VALUE="false"
[ "$CREATE_PROVIDER" = "true" ] && PROVIDER_VALUE="true"

# apply_stack STACK TEMPLATE_FILE PARAMETER... : change set, shown, confirmed, executed. Sets CHANGED when it applied something.
apply_stack() {
  STACK="$1"; TEMPLATE="$2"; shift 2
  say "   change set for the $STACK stack"
  STATE="$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || true)"
  [ "$STATE" = "None" ] && STATE=""
  case "$STATE" in
    "") KIND="CREATE" ;;
    CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE) KIND="UPDATE" ;;
    REVIEW_IN_PROGRESS) KIND="CREATE" ;;
    *) refuse "the $STACK stack is $STATE; a person must repair it before this can run." ;;
  esac
  CHANGE_SET="bootstrap-$(date -u +%Y%m%d%H%M%S)"
  aws cloudformation create-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --change-set-type "$KIND" \
    --template-body "file://$TEMPLATE" --capabilities CAPABILITY_NAMED_IAM --parameters "$@" \
    >/dev/null || fail "could not create the change set for $STACK"
  aws cloudformation wait change-set-create-complete --stack-name "$STACK" --change-set-name "$CHANGE_SET" 2>/dev/null
  CS_STATUS="$(aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --query 'Status' --output text)"
  CS_REASON="$(aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" --query 'StatusReason' --output text)"
  if [ "$CS_STATUS" = "FAILED" ]; then
    case "$CS_REASON" in
      *"didn't contain changes"*|*"No updates are to be performed"*)
        say "   no changes: $STACK already matches its template"
        aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
        return 0
        ;;
      *) fail "the change set for $STACK could not be created: $CS_REASON" ;;
    esac
  fi
  say "   $STACK would change like this:"
  aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" \
    --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table
  if [ -n "$PLAN_ONLY" ]; then
    aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
    say "   --plan-only: change set deleted, nothing applied."
    return 0
  fi
  if [ -z "$YES" ]; then
    printf '   Apply these changes to account %s? Type yes: ' "$ACCOUNT"
    read -r ANSWER
    if [ "$ANSWER" != "yes" ]; then
      aws cloudformation delete-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" >/dev/null 2>&1
      refuse "not confirmed; change set deleted, nothing applied."
    fi
  fi
  aws cloudformation execute-change-set --stack-name "$STACK" --change-set-name "$CHANGE_SET" || fail "could not execute the change set for $STACK"
  say "   executing; waiting for $STACK to finish"
  if [ "$KIND" = "CREATE" ]; then
    aws cloudformation wait stack-create-complete --stack-name "$STACK" || fail "$STACK did not finish creating; read its events"
  else
    aws cloudformation wait stack-update-complete --stack-name "$STACK" || fail "$STACK did not finish updating; read its events"
  fi
  CHANGED="true"
  say "   applied"
}

say "3. The approver stack ($APPROVER_STACK): the roles the role-stack-deploy workflow runs as"
apply_stack "$APPROVER_STACK" "$APPROVER_TEMPLATE" "ParameterKey=GitHubRepository,ParameterValue=$REPO" "ParameterKey=CreateGitHubOidcProvider,ParameterValue=$PROVIDER_VALUE"

if [ -z "$APPROVER_ONLY" ]; then
  say "3b. Emergency path: the pipeline roles stack ($PIPELINE_STACK), applied here instead of by the workflow"
  apply_stack "$PIPELINE_STACK" "$PIPELINE_TEMPLATE" "ParameterKey=GitHubRepository,ParameterValue=$REPO"
fi

if [ -n "$PLAN_ONLY" ]; then
  exit 0
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
ROLES="papyrus-pipeline-roles-plan-github papyrus-pipeline-roles-apply-github papyrus-pipeline-roles-cloudformation"
if [ -z "$APPROVER_ONLY" ]; then
  ROLES="$ROLES papyrus-stack-plan-github papyrus-stack-deploy-github papyrus-stack-deploy-cloudformation"
fi
for ROLE in $ROLES; do
  aws iam get-role --role-name "$ROLE" --query 'Role.RoleName' --output text >/dev/null || fail "role $ROLE does not exist"
  say "   role $ROLE exists"
done
if [ -z "$APPROVER_ONLY" ]; then
  if AWS_ACCOUNT_ID="$ACCOUNT" python3 "$HERE/stack_deploy.py" pipeline-check; then
    :
  else
    fail "the deployed template does not match infra/pipeline/papyrus-stack-pipeline.yaml (see the line above)"
  fi
fi
if [ -n "$CHANGED" ]; then
  say "Done: changes were applied."
else
  say "Done: nothing needed changing."
fi
if [ -n "$APPROVER_ONLY" ]; then
  say "Next, once: infra/pipeline/create-environment.sh --reviewer <github login> creates the approval environment. After that, pipeline role changes are planned and approved in GitHub."
fi
say "Still needed on a NEW account (this script does not do them): see infra/pipeline/README.md, 'A new account, in order'."
exit 0
