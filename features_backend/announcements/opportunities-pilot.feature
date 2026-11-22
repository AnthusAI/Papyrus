Feature: Find a Papyrus Reference that adds something to an X discussion
  An editor supplies safe-to-share References, context-specific search terms, and the point each source supports.
  The pilot finds places to review, not instructions to post. Nothing posts or replies.

  Scenario: An editor sees one strongest candidate per thread and a link suitable for sharing
    When I run the Opportunities command against a saved search with duplicate replies and an already cited source
    Then the review queue has two opportunities with their exact target, original source, and contribution
    And the run counts five read posts and does not follow the next page

  Scenario: The read budget is too small for a minimum-sized request
    When I run the Opportunities command with a maximum of nine reads
    Then the command refuses without searching

  Scenario: No post matches what the newsroom can contribute
    When I run the Opportunities command against a saved search with only an unrelated post
    Then the review queue is empty

  Scenario: Live discovery uses only an authenticated GET and does not follow pagination
    When I run the live Opportunities command with a fake X transport
    Then it requests one Recent Search page of ten posts by GET and never sends a post
