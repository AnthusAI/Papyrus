Feature: One tenant context for every function call
  A function builds the tenant it acts for once, from the AppSync event's identity,
  with one builder in Python and one in TypeScript that read the same test vectors.
  A signed-in caller's tenant comes from its token claims; an IAM caller names the
  tenant explicitly. A shared stack refuses any call that cannot name exactly one
  tenant, and a dedicated stack acts for its fixed site tenant. The tenant is never
  taken from the request body and never guessed.

  Every function that has moved to the context (the list is features_backend/fixtures/function-tenant-context/handlers.json, checked against
  the schema's function list by scripts/test-function-tenant-context.ts) builds it once from the event before it reads anything, and reads
  and writes only through a client scoped to that tenant. The scenarios at the end run the real content-actions handler on an in-memory backend
  that holds the rows of two tenants.

  Scenario: The builder refuses an IAM event that names no tenant
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

  Scenario: A function acts only for the caller's tenant
    A signed-in editor's tenant is the one in its token. The id of another tenant's story is indistinguishable from an id that does not exist:
    the editor is told it was not found, the function never receives the other tenant's row, and it writes nothing to it.
    Given a shared stack with tenants "alpha" and "beta"
    And a "beta" story
    And an "alpha" editor
    When the editor calls saveItemDraft with the id of the "beta" story
    Then the call is refused with "not found" and nothing of "beta" is read or written

  Scenario: An editor's own story is saved for the editor's tenant
    Given a shared stack with tenants "alpha" and "beta"
    And an "alpha" story
    And an "alpha" editor
    When the editor calls saveItemDraft with the id of the "alpha" story
    Then the draft is saved as a story of "alpha"
    And nothing of "beta" is read or written

  Scenario: An IAM call without a tenant is refused on a shared stack
    The platform operator role signs its calls with IAM, which carries no tenant, so on a shared stack the call must name one.
    Given a shared stack with tenants "alpha" and "beta"
    And the platform operator role
    When it invokes content-actions without naming a tenant
    Then the call is refused before any read

  Scenario: The platform operator names the tenant it acts for
    Given a shared stack with tenants "alpha" and "beta"
    And a "beta" story
    And the platform operator role
    When it invokes content-actions for the tenant "alpha" with the id of the "beta" story
    Then the call is refused with "not found" and nothing of "beta" is read or written

  Scenario: A signed-in caller cannot choose another tenant in the request body
    Given a shared stack with tenants "alpha" and "beta"
    And a "beta" story
    And an "alpha" editor
    When the editor calls saveItemDraft with the id of the "beta" story and a body that names the tenant "beta"
    Then the call is refused with "not found" and nothing of "beta" is read or written

  Scenario: A dedicated stack behaves as before
    A dedicated stack serves one site. Its tenant is the fixed one it was built with and a token with no tenant claim is the normal case.
    The call and its answer do not change.
    Given a dedicated stack for the tenant "alpha" with an "alpha" story
    And an editor whose token carries no tenant claim
    When the editor calls saveItemDraft with the id of the "alpha" story
    Then the draft is saved as a story of "alpha"
    And the function acted for the fixed tenant "alpha"

  Scenario: A dedicated stack refuses a token for another tenant
    Given a dedicated stack for the tenant "alpha" with an "alpha" story
    And an "beta" editor
    When the editor calls saveItemDraft with the id of the "alpha" story
    Then the call is refused before any read
