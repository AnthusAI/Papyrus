Feature: Prepare publication routing across separately owned SaaS accounts
  A publication uses the owner's shared central publication router.
  A matched output is prepared for the publication's own section router.
  Preparation does not activate hosting, permission grants or classification.

  Scenario: Unresolved identities and editorial choices remain explicit
    Given an inactive publication routing plan with unresolved identities and criteria
    When the publication routing plan is prepared
    Then publication routing review remains blocked by unresolved fields
    And preparation does not fill in an account, policy or section taxonomy

  Scenario: An internal router cannot use the central owner's account
    Given a synthetic publication routing plan with separately owned routing stages
    And the internal router uses the central owner's account
    When the publication routing plan is prepared
    Then preparation rejects the publication routing plan

  Scenario: The internal router cannot duplicate the central router identity
    Given a synthetic publication routing plan with separately owned routing stages
    And the internal router reuses the central router identity
    When the publication routing plan is prepared
    Then preparation rejects the publication routing plan

  Scenario: Verification failure cannot prepare a section handoff
    Given a synthetic publication routing plan with separately owned routing stages
    And the host rejects the central match receipt
    When a publication section handoff is prepared
    Then no publication section handoff is returned

  Scenario: A verified match retains tenant and source provenance
    Given a synthetic publication routing plan with separately owned routing stages
    And the host verifies a scoped synthetic central match
    When a publication section handoff is prepared
    Then the handoff targets only the consumer's internal router
    And the handoff retains its source revision and central prediction
    And the publication routing plan is still inactive

  Scenario: Existing central decision delivery preserves its original source
    Given a synthetic publication routing plan with separately owned routing stages
    And the host verifies addressed delivery of an existing central match
    When a publication section handoff is prepared
    Then the handoff targets only the consumer's internal router
    And the handoff retains its source revision and central prediction
    And the handoff retains original billing attribution without another provider request
