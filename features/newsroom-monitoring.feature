Feature: The Monitoring page shows the automated research pipeline
  Under Administration, editors and admins read what the collector and router did: the feeds
  watched, recent runs, the collected queue with its routing state, what the shared Cyclotron
  judged relevant to this publication and whether it reached References, and usage against the
  ceilings. The page is read only.

  @brand-agnostic
  Scenario: An editor reads the pipeline for their publication
    Given I open the monitoring newsroom at 1280 by 900
    Then the monitoring page should show the section "Feeds watched"
    And the monitoring page should show the section "Recent runs"
    And the monitoring page should show the section "Collected queue"
    And the monitoring page should show the section "Usage"
    And the monitoring queue should list "Quantum paper on arXiv" as "Routed"
    And the monitoring queue should offer a link to the References entry for "Quantum paper on arXiv"
    And the monitoring queue should say "Not in the References queue: delivery failed" for "Phishing kit leaks"
    And the monitoring usage should read "2 of 100" and "3 of 300"
    And the monitoring page should not name any other publication
    And no browser console errors should occur

  @brand-agnostic
  Scenario: An admin widens the page to the whole shared pipeline
    Given I open the monitoring newsroom at 1280 by 900
    When I choose the whole shared pipeline
    Then the monitoring queue should list the judgement for every publication
    And no browser console errors should occur
