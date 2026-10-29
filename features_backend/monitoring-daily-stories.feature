@backend @monitoring-daily-stories
Feature: Every day the monitoring router drafts a story for each accepted item its monitors found
  A monitor delivers pending References into a publication. Editors accept some, and the automatic acceptance accepts the confident ones
  nobody voted on. Once a day, at a quiet hour, the monitoring router runs the task "monitor-stories": for each publication it writes a
  short cited story draft from every accepted, monitored Reference that has no draft yet, ranked by the relevance Cyclotron's verdict so the
  best items go first. A draft is a private story_draft Proposal that cites its source, and each publication gets one soft review request
  per run; nothing is published, and an editor approves the copy. A Reference is never drafted twice. The task does not need the
  knowledge-run stack, and it is on for every publication unless the publication's router entry says "monitorStories": {"enabled": false}.
  There is no fixed number of drafts per run. The run is bounded only by real constraints: the Lambda's remaining time, shared equally by
  the publications still to run (a publication the time stopped gets another turn while time is left), a model-spend backstop, and a
  draft that cannot be filed. Each publication logs one JSON line: how many it drafted, how many candidates it found, how many pending
  References it did not read, how many it skipped, and what stopped it. The model, the pages and the backends are fakes in these
  scenarios and nothing touches production.

  Background:
    Given a router with the publication "example-site" and no monitorStories setting

  Scenario: The daily run drafts each accepted undrafted monitored Reference once
    Given 3 accepted References that the "hn" monitor delivered
    When the router runs its daily monitor stories
    Then 3 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 3, candidates 3, notAccepted 0, skipped 0 and stoppedBy none
    When the router runs its daily monitor stories again
    Then still only 3 story drafts are filed
    And the log line for "example-site" says drafted 0, candidates 0, notAccepted 0, skipped 0 and stoppedBy none

  Scenario: There is no fixed number of drafts per run
    Given 7 accepted References that the "hn" monitor delivered
    When the router runs its daily monitor stories
    Then 7 story drafts are filed, one per Reference, each citing its source

  Scenario: Pending References are skipped and counted
    Given 2 accepted References that the "hn" monitor delivered
    And 2 pending References that the "hn" monitor delivered
    When the router runs its daily monitor stories
    Then 2 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 2, candidates 2, notAccepted 2, skipped 0 and stoppedBy none

  Scenario: A publication that turns monitor stories off is skipped
    Given the publication's monitorStories setting is {"enabled": false}
    And 3 accepted References that the "hn" monitor delivered
    When the router runs its daily monitor stories
    Then no story draft is filed and the model is never asked
    And the log line for "example-site" says status "disabled" and drafted 0

  Scenario: Running out of time stops cleanly and the next run continues
    Given 5 accepted References that the "hn" monitor delivered
    And the Lambda runs out of time after 2 drafts
    When the router runs its daily monitor stories
    Then 2 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 2, candidates 5, notAccepted 0, skipped 0 and stoppedBy "time"
    When the router runs its daily monitor stories again with time to spare
    Then 5 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 3, candidates 3, notAccepted 0, skipped 0 and stoppedBy none

  Scenario: The best ranked items are drafted first when time runs out
    Given 4 accepted References that the "hn" monitor delivered, which the Cyclotron judged relevant with 20%, 90%, 40% and 70% confidence
    And the Lambda runs out of time after 2 drafts
    When the router runs its daily monitor stories
    Then the drafts filed are for References 2 and 4

  Scenario: A TTAB Reference that an Automation is making a story for is skipped
    Given 2 accepted References that the "ttab" monitor delivered
    And 1 accepted Reference that the "hn" monitor delivered
    And an enabled Automation that is triggered by the "ttab" monitor
    And the Automation has a procedure run in progress for the first "ttab" Reference
    When the router runs its daily monitor stories
    Then 2 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 2, candidates 2, notAccepted 0, skipped 0, stoppedBy none and handledByAutomation 1

  Scenario: A TTAB Reference that an Automation already wrote a story for is skipped
    Given 2 accepted References that the "ttab" monitor delivered
    And an enabled Automation that is triggered by the "ttab" monitor
    And the Automation has already written a story based on the first "ttab" Reference
    When the router runs its daily monitor stories
    Then 1 story draft is filed, for the "ttab" Reference
    And the log line for "example-site" says drafted 1, candidates 1, notAccepted 0, skipped 0, stoppedBy none and handledByAutomation 1

  Scenario: A Reference whose Automation never ran is drafted like any other
    Given 2 accepted References that the "ttab" monitor delivered
    And an enabled Automation that is triggered by the "ttab" monitor
    When the router runs its daily monitor stories
    Then 2 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 2, candidates 2, notAccepted 0, skipped 0, stoppedBy none and handledByAutomation 0

  Scenario: Distinctive Mark's web-search finds are drafted and so are its TTAB rulings its Automation has not taken on
    Given 2 accepted References that the "ttab" monitor delivered
    And 2 accepted References that the "web-distinctive" monitor delivered
    And an enabled Automation that is triggered by the "ttab" monitor
    And the Automation has a procedure run in progress for the first "ttab" Reference
    When the router runs its daily monitor stories
    Then 3 story drafts are filed, one per Reference, each citing its source
    And the log line for "example-site" says drafted 3, candidates 3, notAccepted 0, skipped 0, stoppedBy none and handledByAutomation 1

  Scenario: A publication with a backlog does not starve the others
    Given a second publication "other-site" with 2 accepted References that the "hn" monitor delivered
    And 8 accepted References that the "hn" monitor delivered
    And every draft takes 60 seconds of a 600 second Lambda
    When the router runs its daily monitor stories
    Then the log line for "other-site" says drafted 2 and stoppedBy none
    And the log line for "example-site" says stoppedBy "time"

  Scenario: A draft that cannot be filed stops the publication before more money is spent
    Given 4 accepted References that the "hn" monitor delivered
    And the backend refuses to file proposals
    When the router runs its daily monitor stories
    Then the model was asked exactly once
    And the log line for "example-site" says drafted 0 and stoppedBy "file_error"
