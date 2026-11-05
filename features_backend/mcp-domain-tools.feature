Feature: Site tools preserve editorial and reader authority
  Editors and readers use structured site tools in their own authority. A stale card must not overwrite a newer decision.

  Scenario: An editor reads the current Story and its evidence
    Given an editor connected to a site with a Story and evidence
    When the editor asks for the Story and its evidence
    Then the tools return the current Story version and the evidence lineage

  Scenario: A stale card cannot change a Reference
    Given an editor connected to a site with a Story and evidence
    When the editor decides a Reference using an obsolete revision
    Then the decision is refused without changing the Reference

  Scenario: A reader cannot use staff tools
    Given a reader connected to a site with a verified site subject
    When the reader asks for the Story
    Then the staff tool is refused

  Scenario: A reader submission uses the verified site subject
    Given a reader connected to a site with a verified site subject
    When the reader submits a link
    Then the site's reader policy receives the verified site subject
