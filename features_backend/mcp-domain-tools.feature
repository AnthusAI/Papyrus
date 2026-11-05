Feature: Site tools preserve editorial and reader authority
  Editors and readers use structured site tools in their own authority. A stale card must not overwrite a newer decision.

  Scenario: An editor reads the current Story and its evidence
    Given an editor connected to a site with a Story and evidence
    When the editor asks for the Story and its evidence
    Then the tools return the current Story version and the evidence lineage

  Scenario: A site without conditional writes refuses a Reference decision
    Given an editor connected to a site with a Story and evidence
    When the editor decides a Reference without a conditional-write adapter
    Then the decision is refused without changing the Reference

  Scenario: A reader cannot use staff tools
    Given a reader connected to a site with a verified site subject
    When the reader asks for the Story
    Then the staff tool is refused

  Scenario: A reader submission uses the verified site subject
    Given a reader connected to a site with a verified site subject
    When the reader submits a link
    Then the site's reader policy receives the verified site subject

  Scenario: A Reference card identifies its current version and revision
    Given an editor connected to a site with a current Reference
    When the editor opens the Reference by its lineage
    Then the Reference card identifies the current version and revision

  Scenario: A tenant cannot read a Reference without an ownership key
    Given an editor connected to a shared site with a current Reference
    When the editor opens the Reference by its lineage
    Then the Reference read is refused

  Scenario: An agent accepts the Reference shown on a current card
    Given an editor connected to a site with a current Reference
    When the agent accepts the Reference shown on the card
    Then the site receives the current version and revision for an agent decision

  Scenario: An outdated Reference card cannot be accepted
    Given an editor connected to a site with a current Reference
    When the agent accepts an outdated Reference card
    Then the Reference decision is refused
