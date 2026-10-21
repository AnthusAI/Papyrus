Feature: The Monitoring page shows the automated research pipeline to editors
  Editors and admins can see what the collector and router did, read-only. An editor sees only what
  is relevant to their own publication; an admin can switch to the whole shared pipeline.

  Scenario: An editor sees the pipeline as it concerns their publication
    Given a monitoring table with runs, routed items and a ceiling configuration
    When an editor of "anth-us" opens the monitoring overview
    Then the feed "hn" is watched on a 15 minute schedule and is enabled
    And the recent runs list the newest first with new, unchanged and error counts
    And the router is live with feedback on
    And usage reads 2 of 100 decisions today and 3 of 300 in total
    And the queue shows only relevance for "anth-us"
    And the item "Quantum paper on arXiv" is relevant with confidence 0.91 and reached the References queue
    And the item "Phishing kit leaks" is relevant but did not reach the References queue
    And 1 item judged not relevant to the publication is not listed

  Scenario: An admin can read the whole shared pipeline
    Given a monitoring table with runs, routed items and a ceiling configuration
    When an admin opens the monitoring overview for the whole pipeline
    Then the item "Quantum paper on arXiv" shows relevance for "anth-us", "p-apyr-us" and "threat-intelligence"
    And the item "A recipe for sourdough" is listed

  Scenario: An editor cannot read the whole pipeline
    Given a monitoring table with runs, routed items and a ceiling configuration
    When an editor of "anth-us" asks for the whole pipeline
    Then the request is refused

  Scenario: A reader cannot read monitoring at all
    Given a monitoring table with runs, routed items and a ceiling configuration
    When a reader opens the monitoring overview
    Then the request is refused

  Scenario: Nothing has been collected yet
    Given an empty monitoring table
    When an editor of "anth-us" opens the monitoring overview
    Then the overview says nothing is configured or collected yet

  Scenario: The overview never exposes endpoints, roles or accounts
    Given a monitoring table with runs, routed items and a ceiling configuration
    When an admin opens the monitoring overview for the whole pipeline
    Then the overview contains no endpoint, role ARN, account or run identifier of the shared Cyclotron
