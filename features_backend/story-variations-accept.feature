Feature: Accepting a variation makes its wording the Story's next version and records where it came from
  An editor who accepts a variation (PPY-9e7a4a) makes that wording the Story's next version. The newsroom saves it as a new version through the same action as
  any edit, with the variation's id in the version's front matter as `variationId`, so the Story's history shows which version came from which variation.
  A Story has one accepted variation at a time: accepting another variation makes another version and puts the earlier variation back on offer, and the first
  wording stays in the version history. Rejecting changes nothing on the Story and keeps the reason. On a backend whose records carry a tenant, as Machines on Machines'
  does, the new version is the tenant's like every version before it.

  Background:
    Given a Story at version 1 with the headline "Foo checks claims against sources"
    And a run offered variations "Reference angle" and "Story angle" to the Story

  Scenario: The accepted wording is the next version and says which variation it came from
    When an editor accepts variation 2 in the newsroom saying "This is the real disagreement"
    Then the Story is at version 2 with the headline "Story angle headline"
    And version 2 says its wording came from variation 2
    And version 1 says nothing about a variation
    And variation 2 is accepted with the reason "This is the real disagreement"
    And variation 1 is on offer

  Scenario: Accepting a second variation makes a second version and puts the first back on offer
    When an editor accepts variation 1 in the newsroom saying "For now"
    And an editor accepts variation 2 in the newsroom saying "Better"
    Then the Story is at version 3 with the headline "Story angle headline"
    And the Story's history shows version 2 from variation 1 and version 3 from variation 2
    And variation 2 is accepted with the reason "Better"
    And variation 1 is on offer

  Scenario: Rejecting a variation changes nothing on the Story
    When an editor rejects variation 1 in the newsroom saying "Only restates the source"
    Then the Story is at version 1 with the headline "Foo checks claims against sources"
    And variation 1 is rejected with the reason "Only restates the source"
    And variation 2 is on offer

  Scenario: On a backend whose records carry a tenant the new version is the tenant's
    Given the Story belongs to the tenant "machines-on-machines"
    When an editor accepts variation 1 in the newsroom saying "Fits"
    Then version 2 belongs to the tenant "machines-on-machines"
    And version 1 is superseded
