Feature: One tenant context for every function call
  A function builds the tenant it acts for once, from the AppSync event's identity,
  with one builder in Python and one in TypeScript that read the same test vectors.
  A signed-in caller's tenant comes from its token claims; an IAM caller names the
  tenant explicitly. A shared stack refuses any call that cannot name exactly one
  tenant, and a dedicated stack acts for its fixed site tenant. The tenant is never
  taken from the request body and never guessed.

  Scenario: An IAM call without a tenant is refused on a shared stack
    Given tenancy mode shared and an IAM event with no tenant
    When the context is built
    Then it raises a refusal before any read
    And the refusal reason is "iam_without_tenant" in Python and in TypeScript

  Scenario: A member's claims give one tenant and its roles
    Given tenancy mode shared and a signed-in event whose member claim is "alpha"
    When the context is built
    Then the tenant is "alpha" with the roles "member" in Python and in TypeScript

  Scenario: Claims naming two tenants are refused
    Given tenancy mode shared and a signed-in event with an admin claim "alpha" and a member claim "beta"
    When the context is built
    Then it raises a refusal before any read
    And the refusal reason is "multiple_tenants" in Python and in TypeScript

  Scenario: A dedicated stack returns its fixed tenant and refuses a foreign claim
    Given a dedicated stack for tenant "alpha" and a signed-in event whose editor claim is "alpha"
    When the context is built
    Then the tenant is "alpha" with the roles "editor" in Python and in TypeScript
    Given a dedicated stack for tenant "alpha" and a signed-in event whose editor claim is "beta"
    When the context is built
    Then it raises a refusal before any read
    And the refusal reason is "foreign_tenant" in Python and in TypeScript

  Scenario: A dedicated stack with no tenant behaves as it does today
    Given a dedicated stack with no tenant and a signed-in event with no claims
    When the context is built
    Then the tenant is none with no roles in Python and in TypeScript
