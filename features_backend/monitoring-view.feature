Feature: The Monitoring page shows the automated research pipeline to editors
  Editors and admins can see what the collector and router did, read-only. An editor sees only what
  is relevant to their own publication; an admin can switch to the whole shared pipeline.

  Scenario: An editor sees the pipeline as it concerns their publication
    Given a monitoring table with runs, routed items and a legacy quota configuration
    When an editor of "anth-us" opens the monitoring overview
    Then the feed "hn" is watched on a 15 minute schedule and is enabled
    And the recent runs list the newest first with new, unchanged and error counts
    And the router is live and sends editor feedback
    And usage reports 2 decisions today and 3 recorded decisions in inspected history without quotas
    And the queue shows only relevance for "anth-us"
    And the item "Quantum paper on arXiv" is relevant with confidence 0.91 and reached the References queue
    And the item "Phishing kit leaks" is relevant but did not reach the References queue
    And 1 item judged not relevant to the publication is not listed

  Scenario: An admin can read the whole shared pipeline
    Given a monitoring table with runs, routed items and a legacy quota configuration
    When an admin opens the monitoring overview for the whole pipeline
    Then the item "Quantum paper on arXiv" shows relevance for "anth-us", "p-apyr-us" and "threat-intelligence"
    And the item "A recipe for sourdough" is listed

  Scenario: An editor cannot read the whole pipeline
    Given a monitoring table with runs, routed items and a legacy quota configuration
    When an editor of "anth-us" asks for the whole pipeline
    Then the request is refused

  Scenario: A reader cannot read monitoring at all
    Given a monitoring table with runs, routed items and a legacy quota configuration
    When a reader opens the monitoring overview
    Then the request is refused

  Scenario: Nothing has been collected yet
    Given an empty monitoring table
    When an editor of "anth-us" opens the monitoring overview
    Then the overview says nothing is configured or collected yet

  Scenario: Email receipts use the publication's configured receiver partition
    Given a separate private email receiver partition for "p-apyr-us"
    When an editor of "p-apyr-us" opens the monitoring overview with that partition
    Then the shared feed still comes from the "hn" partition
    And the email receipt appears from the "p-apyr-us-email" partition

  Scenario: The overview never exposes endpoints, roles or accounts
    Given a monitoring table with runs, routed items and a legacy quota configuration
    When an admin opens the monitoring overview for the whole pipeline
    Then the overview contains no endpoint, role ARN, account or run identifier of the shared Cyclotron

  Scenario: A site sees only the monitors that are routed to it
    Given monitors "hn", "ttab" and "huggingface" where only "ttab" routes to the publication "distinctive"
    When an editor of "distinctive" opens the monitoring overview
    Then the queue lists only the items of the monitor "ttab"
    And the item "Decision on a mark" is waiting for the router
    And no item of the monitors "hn" and "huggingface" is returned
    And the monitors "hn" and "huggingface" are named as not routed to this site

  Scenario: Every email receipt is reachable by paging, newest first
    Given a monitoring table with 45 email receipts for "anth-us"
    When an editor of "anth-us" opens the monitoring overview
    Then the first page lists 20 email receipts, newest first, and offers more
    When the editor loads more email receipts until the list ends
    Then all 45 email receipts have been listed exactly once

  Scenario: An old held email is always findable with the Held for review filter
    Given a monitoring table with 70 email receipts for "anth-us" where the oldest is held for review
    When an editor of "anth-us" opens the monitoring overview
    Then the oldest receipt is not on the first page
    When the editor filters to "Held for review"
    Then the oldest receipt is listed as held for review
    And the held filter lists nothing that was not held

  Scenario: The collector and router lists keep paging past their page size
    Given a monitoring table with 40 more collector runs and 40 more router runs
    When an editor of "anth-us" opens the monitoring overview
    Then the first page of runs offers more
    When the editor loads more runs until the list ends
    Then every collector run has been listed exactly once
