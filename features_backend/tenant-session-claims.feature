Feature: A signed-in session acts for one tenant, carried as role claims in the token
  A person who signs in to the newsroom acts for exactly one site at a time. Cognito's pre-token-generation trigger
  (event version 2, so the claims land on the access token that the data client sends) reads the person's
  TenantMembership row for the site they selected and writes one claim for the role they hold there:
  papyrus_tenant_admin, papyrus_tenant_editor, papyrus_tenant_curator or papyrus_tenant_member, each holding the tenant
  id. The Google sign-in flow cannot pass the chosen site to the trigger, so the choice is stored on the stack in a
  TenantSelection row keyed by the person's sign-in id, and the trigger reads that. The trigger reads only those two
  local rows, never Prospectus, so sign-in does not wait on anyone. A person with no membership gets no tenant claim.
  A dedicated stack serves one fixed site, so it emits the claims for that site from the person's Cognito groups or
  membership and ignores any selection. The claims are added beside the existing Cognito groups, which are left as they
  are, and no authorisation rule reads the claims yet. There is no sandbox account (decision D9), so these scenarios
  drive the real handler with stubbed Cognito events and an in-memory copy of the two models.

  Scenario: A member of two sites acts for one at a time
    Given Ada is an editor of "alpha" and a member of "beta" on a shared stack
    When she signs in and selects "alpha"
    Then her access token carries papyrus_tenant_editor "alpha" and no claim for "beta"
    And her ID token carries the same claims
    When she switches to "beta"
    Then her access token carries papyrus_tenant_member "beta" and no editor claim

  Scenario: A person with no membership has no tenant
    Given Bo has a Google account and no TenantMembership on a shared stack
    When he signs in to the newsroom
    Then his token has no tenant claim
    And a function that builds its tenant context from that token refuses the call as "no_tenant_claim"

  Scenario: A person who has not selected a site has no tenant
    Given Ada is an editor of "alpha" and a member of "beta" on a shared stack
    When she signs in without having selected a site
    Then her token has no tenant claim

  Scenario: A selection without a membership grants nothing
    Given Bo has a Google account and no TenantMembership on a shared stack
    When he selects "alpha" and signs in
    Then his token has no tenant claim

  Scenario: A removed member loses access at the next token refresh
    Given Ada is an editor of "alpha" on a shared stack and has selected "alpha"
    And her token carries papyrus_tenant_editor "alpha"
    When Ada is removed from the Account that owns "alpha" and her membership is revoked
    And her token is next refreshed
    Then it carries no "alpha" claim

  Scenario: A member whose membership row is deleted loses access at the next token refresh
    Given Ada is an editor of "alpha" on a shared stack and has selected "alpha"
    When her TenantMembership row is deleted and her token is next refreshed
    Then it carries no "alpha" claim

  Scenario: Cognito groups do not give a tenant claim on a shared stack
    Given Cy belongs to the Cognito group "admin" and has no TenantMembership on a shared stack
    When Cy signs in
    Then his token has no tenant claim
    And his Cognito groups are left as they were

  Scenario: A dedicated stack emits its fixed tenant for a person in a matching group
    Given a dedicated stack for tenant "alpha" and Dee in the Cognito groups "editor" and "curator"
    When Dee signs in
    Then her token carries papyrus_tenant_editor "alpha" and papyrus_tenant_curator "alpha" only
    And her token carries no admin or member claim
    And her Cognito groups are left as they were

  Scenario: A dedicated stack emits its fixed tenant for a person with a membership
    Given a dedicated stack for tenant "alpha" and Eli with an active member membership of "alpha" and no group
    When Eli signs in
    Then his token carries papyrus_tenant_member "alpha"

  Scenario: A dedicated stack ignores a selection of another site
    Given a dedicated stack for tenant "alpha" and Dee in the Cognito group "editor"
    And Dee has selected "beta" and holds an admin membership of "beta"
    When Dee signs in
    Then her token carries papyrus_tenant_editor "alpha" and no claim for "beta"

  Scenario: A dedicated stack with no tenant emits no claims
    Given a dedicated stack with no tenant and Dee in the Cognito group "editor"
    When Dee signs in
    Then her token has no tenant claim

  Scenario: A dedicated stack with the tenancy models left out still emits group claims
    Given a dedicated stack for tenant "alpha" whose tenancy models are not deployed and Dee in the Cognito group "admin"
    When Dee signs in
    Then her token carries papyrus_tenant_admin "alpha"

  Scenario: A shared stack whose tenancy models are not deployed emits no claims
    Given a shared stack whose tenancy models are not deployed and Ada in the Cognito group "admin"
    When Ada signs in
    Then her token has no tenant claim

  Scenario: Only an active membership of the selected site counts
    Given Ada has an editor membership of "alpha" with status "pending" on a shared stack and has selected "alpha"
    When Ada signs in
    Then her token has no tenant claim

  Scenario: The trigger is wired for event version two on the Essentials plan
    When the site backend is synthesised with a shared tenancy stack
    Then the user pool's pre-token-generation trigger is the tenant claims function at event version "V2_0"
    And the user pool has no version one pre-token-generation trigger
    And the user pool plan is "ESSENTIALS"
    And the tenant claims function is told the tenancy models are deployed
    And the tenant claims function can query the data API and cannot write to it
    And the auth stack does not depend on the data stack

  Scenario: The first deploy of a new site keeps the trigger and leaves the tenancy models to the second deploy
    When the site backend is synthesised for the bootstrap stage
    Then the user pool's pre-token-generation trigger is the tenant claims function at event version "V2_0"
    And the tenant claims function is not told the tenancy models are deployed
