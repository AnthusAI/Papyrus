Feature: A soft review's deadline is a timer, and review requests are read by index
  A soft review may have a deadline. Until now the deadline was checked only when someone read the list, so a request nobody looked at never proceeded. Now
  the deadline is a follow-up timer on the site's schedule group: raising the request sets it, and at the deadline its wake records "proceeded without
  review" with nobody looking. The wake reads the request again first, so an answer or a withdrawal before the deadline means it does nothing; an answer
  given where the timers are at hand also deletes the timer. A flag and a hard gate never have a deadline, so they never have a timer. Every request is
  in one partition of the state index (open, answered, timed out, withdrawn): the Notification Center, the library and the tools read the partition they
  need, the publish gate reads its requests by their ids, and nothing lists the whole review request table. A deadline whose wake was lost is Overdue
  and its wake is sent again with its original key. The deadline wake is the engine's own work, not an agent's: the runner starts its procedure with no
  adopted automation, for owners on the engine list only, and the site's pause still stops it.

  Background:
    Given a site with deadline timers whose review requests can only be read by index or by id

  Scenario: A soft review proceeds at its deadline with nobody looking
    When the procedure "ideas" raises a soft review with the deadline "2026-11-20T09:00:00Z"
    Then the site's timers hold one entry, for that request's deadline
    When the time "2026-11-20T09:00:00Z" arrives with no page open
    Then the request is timed out with the note "proceeded without review"
    And the request has no due time and is in the "timed_out" partition of the state index
    And the site's timers hold no entry

  Scenario: An answer before the deadline cancels the timer
    When the procedure "ideas" raises a soft review with the deadline "2026-11-20T09:00:00Z"
    And an editor approves the request on "2026-11-19T15:00:00Z" where the site's timers are at hand
    Then the site's timers hold no entry
    When the time "2026-11-21T09:00:00Z" arrives with no page open
    Then no deadline wake ran
    And the request is answered with "approve"

  Scenario: An answer from the Notification Center leaves the timer, whose wake then does nothing
    When the procedure "ideas" raises a soft review with the deadline "2026-11-20T09:00:00Z"
    And an editor approves the request on "2026-11-19T15:00:00Z" from the Notification Center, which has no timers
    Then the site's timers hold one entry, for that request's deadline
    When the time "2026-11-20T09:00:00Z" arrives with no page open
    Then the deadline wake did nothing because the request waits for nothing now
    And the request is answered with "approve"

  Scenario: A withdrawal before the deadline cancels the timer
    When the procedure "ideas" raises a soft review with the deadline "2026-11-20T09:00:00Z"
    And the procedure withdraws the request where the site's timers are at hand
    Then the site's timers hold no entry
    And the request has no due time and is in the "withdrawn" partition of the state index

  Scenario: A hard gate never times out and has no timer
    When the procedure "ruling" raises a hard gate
    Then the request has no due time and is in the "open" partition of the state index
    And the site's timers hold no entry
    When the time "2027-11-20T09:00:00Z" arrives with no page open
    Then the request is still open
    And raising a hard gate with a deadline is refused

  Scenario: A flag has no deadline and no timer
    When the procedure "ideas" raises a flag
    Then the request has no due time and is in the "open" partition of the state index
    And the site's timers hold no entry

  Scenario: A soft review with a deadline needs the site's timers
    Then raising a soft review with a deadline but no timers is refused, and nothing is stored

  Scenario: The publish gate finds its requests by their ids
    Given the site's publish gate requires a person's approval
    When an agent publishes the story "story-1"
    Then publishing is refused and the request "rr-publish" for that version is open
    When the publish gate's request is withdrawn
    And an agent publishes the story "story-1"
    Then publishing is refused and the request "rr-publish-2" for that version is open
    When an editor approves the publish gate's latest request
    And an agent publishes the story "story-1"
    Then publishing is allowed
    And the publish gate read its requests by their ids

  Scenario: Reads of review requests go to the state index, never to the whole table
    Given open, answered and withdrawn review requests
    When the requests are listed by state, listed in every state, read back for steering and their recipients resolved
    Then the open list holds only the open requests and the full list holds every request
    And every read of review requests was a query of a state partition or a read by id

  Scenario: A deadline whose wake was lost is Overdue, and its wake is sent again with its original key
    When the procedure "ideas" raises a soft review with the deadline "2026-11-20T09:00:00Z"
    And its deadline timer fires into a queue that lost the wake
    Then on "2026-11-20T12:00:00Z" the request is listed as Overdue, in words with a mark
    When the hygiene agent's daily wake recovers what is overdue on "2026-11-20T12:00:00Z"
    Then the wake sent again has the key the request's own timer used
    And running that wake times the request out with the note "proceeded without review"

  # The engine's own follow-ups (owner decision, Ryan, 2026-11-22): the runner starts a deadline wake with no adopted agent. Only owners on the engine list,
  # with their own procedure, are started this way; the site's pause still stops them.

  Scenario: A deadline wake from the queue runs with no automation adopted and times the request out
    Given a site backend with the published procedure "review_deadline"
    And the open soft review "rr-soft" waits for its deadline "2026-11-20T09:00:00Z"
    When the deadline timer's wake for "rr-soft" reaches the runner
    Then the procedure ran once
    And the run record is acted with the reason "timed_out" and names no responsibility and no rung
    And the review request "rr-soft" proceeded without review

  Scenario: A follow-up wake for an owner that is not on the engine list is still skipped
    Given a site backend with the published procedure "review_deadline"
    And the open soft review "rr-soft" waits for its deadline "2026-11-20T09:00:00Z"
    When a follow-up wake for "rr-soft" from the owner "some-agent" reaches the runner
    Then no procedure ran
    And the run record says nothing to do with the reason "not_adopted"
    And the review request "rr-soft" is still open

  Scenario: A wake that names the engine owner but another procedure is still skipped
    Given a site backend with the published procedure "rate_items"
    And the open soft review "rr-soft" waits for its deadline "2026-11-20T09:00:00Z"
    When the deadline timer's wake for "rr-soft" reaches the runner naming the procedure "rate_items"
    Then no procedure ran
    And the run record says nothing to do with the reason "not_adopted"

  Scenario: A paused site starts no engine follow-up either
    Given a site backend with the published procedure "review_deadline"
    And an admin paused the site because "Incident"
    And the open soft review "rr-soft" waits for its deadline "2026-11-20T09:00:00Z"
    When the deadline timer's wake for "rr-soft" reaches the runner
    Then no procedure ran
    And the run record says nothing to do with the reason "paused"
    And the review request "rr-soft" is still open
