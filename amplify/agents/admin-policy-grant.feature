Feature: A signed-in admin may save the agent policy document, and no one else may through a role
  `papyrus agents set-rung --apply` puts the next version of the policy at `tenants/<tenant>/site/agents/<version>.json` in the site's media bucket, with the
  signed-in person's own credentials. Amplify's storage rules take a prefix ending in `/*` and this key has a wildcard in the middle, so the grant is an
  inline policy on the `admin` group's role, in a stack of its own so the storage and auth stacks do not depend on each other. It allows get and put on that
  prefix and nothing else: no delete (every version stays), no list. The editor and curator groups and the plain authenticated role get nothing.
  A shared stack does not get it, because the prefix names every tenant. Executable by scripts/test-admin-agent-policy-grant.ts.

  Scenario: The admin group's role may get and put the policy versions
    Given a dedicated site's backend
    Then the admin group's role has one statement on "tenants/*/site/agents/*" in the media bucket
    And the statement allows "s3:GetObject" and "s3:PutObject" and nothing else

  Scenario: No other role carries the grant
    Given a dedicated site's backend
    Then the editor group's role does not carry the statement
    And the storage rules do not name the agent policy prefix

  Scenario: A shared stack does not carry the grant
    Given a shared stack's backend
    Then no role has the statement
