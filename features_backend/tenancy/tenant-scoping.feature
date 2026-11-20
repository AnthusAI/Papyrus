Feature: One backend serving several tenants
  Each tenant's Sections, articles and site cyclotron are its own. Rows written
  before tenant scoping are adopted into a tenant by an explicit, repeatable
  command that previews before it writes.

  Scenario: Two tenants with the same Section key each list only their own Sections
    Given a backend shared by the tenants "alpha" and "beta"
    And tenant "alpha" has the Section "mission" titled "Alpha Mission"
    And tenant "beta" has the Section "mission" titled "Beta Mission"
    When tenant "alpha" renames the Section "mission" to "Alpha Renamed"
    Then tenant "alpha" lists only the Section titles "Alpha Renamed"
    And tenant "beta" lists only the Section titles "Beta Mission"

  Scenario: Tenant alpha importing Markus content leaves tenant beta's same-slug article unchanged
    Given a backend shared by the tenants "alpha" and "beta"
    And tenant "beta" has imported its content directory
    When tenant "alpha" imports its content directory
    Then tenant "beta" still has exactly the items it imported
    And tenant "alpha" has its own items with the same slugs

  @requires-cyclotron
  Scenario: Two tenants with different Sections each get a site cyclotron with only their own Sections
    Given a backend shared by the tenants "alpha" and "beta"
    And tenant "alpha" has the Section "security" titled "Security"
    And tenant "alpha" has the Section "cloud" titled "Cloud"
    And tenant "beta" has the Section "security" titled "Security"
    And tenant "beta" has the Section "policy" titled "Policy"
    When each tenant's site cyclotron is built
    Then tenant "alpha" has a site cyclotron with the Sections "cloud, security"
    And tenant "beta" has a site cyclotron with the Sections "policy, security"
    And the two site cyclotrons have different ids

  Scenario: Legacy bare-id rows are adopted by the dry run then the apply and a second apply changes nothing
    Given a backend holding rows written before tenant scoping
    When the adoption dry run for tenant "alpha" is run
    Then it would adopt 2 items and re-id 2 Sections
    And nothing was written to the legacy backend
    When the adoption for tenant "alpha" is applied
    Then tenant "alpha" sees the Section "mission" by id and 2 items by list
    And the media storage path is unchanged
    When the adoption for tenant "alpha" is applied
    Then nothing was written to the legacy backend
