Feature: Human review points let any step ask a person without making review a story state
  Any step in a site's automation can raise a review request about an item: a story, a proposal, a
  reference, an automation run, a Cyclotron decision, or a batch of those. A request has a reason, a question
  and one of three modes. A flag is informational and nothing waits. A soft review makes the process wait until
  a deadline and, if nobody answers, lets it proceed and records "proceeded without review". A hard gate never
  proceeds without an explicit answer. An editor or admin answers with approve, reject or feedback, and may
  steer: feedback is stored on the request and handed back to whatever raised it, which records the run that
  used it. The deadline is checked whenever the request is read. Who is told is site configuration, by mode or
  by automation, defaulting to the site owner, and can change without a code change.

  Scenario: A flag never makes the process wait
    Given a site with no review requests
    When the procedure "ideas" raises a flag on story "story-1" saying "Two sources disagree"
    And the procedure waits for the review
    Then the wait returns at once and the request is still open
    And the request has no deadline

  Scenario: A soft review that nobody answers proceeds at its deadline and says so
    Given a site with no review requests
    When the procedure "ideas" raises a soft review on story "story-1" with a deadline in 7 days
    And the procedure waits for the review until nobody has answered
    Then the process proceeds
    And the request is timed out with the note "proceeded without review"
    And the request can no longer be answered

  Scenario: A soft review answered in time returns the answer instead
    Given a site with no review requests
    When the procedure "ideas" raises a soft review on story "story-1" with a deadline in 7 days
    And the editor answers with feedback "Shorter, and more on pricing" and the steer "adjust"
    Then the outcome is "feedback"
    And the feedback "Shorter, and more on pricing" is returned to the procedure

  Scenario: A hard gate blocks indefinitely
    Given a site with no review requests
    When the procedure "ruling" raises a hard gate on story "story-1" saying "Approve this ruling summary"
    And a year goes by with nobody answering
    Then the process has not proceeded
    And the request is still open
    And the request has no deadline

  Scenario: A hard gate continues only on an explicit approval
    Given a site with no review requests
    When the procedure "ruling" raises a hard gate on story "story-1" saying "Approve this ruling summary"
    And the editor answers with approve
    Then the outcome is "approved"

  Scenario: Only editors and admins answer
    Given a site with no review requests
    When the procedure "ideas" raises a soft review on story "story-1" with a deadline in 7 days
    Then a reader who tries to answer is refused because only editors and admins can answer

  Scenario: Steering is read back by whatever raised the request and recorded when it is used
    Given a site with no review requests
    When the procedure "idea-pipeline" raises a soft review on story "story-1" with a deadline in 7 days
    And the editor answers with feedback "Fewer listicles" and the steer "not_this_kind"
    Then "idea-pipeline" reads the steering "Fewer listicles"
    When "idea-pipeline" records that run "run-42" used the steering
    Then the request shows it was applied in run "run-42"
    And "idea-pipeline" has no unapplied steering

  Scenario: The idea pipeline raises one soft review per synthesis run
    Given a site with no review requests
    When the idea pipeline raises a batch review for run "2026-W43" with 3 proposals
    Then there is one open soft review "3 new story ideas to review"
    And its deadline is 7 days away
    When the idea pipeline raises the batch review for run "2026-W43" again
    Then there is still one review request

  Scenario: Recipients come from site configuration and the most specific rule wins
    Given a site whose admin is "admin@example.test" and whose editor is "ed@example.test"
    When no recipient rule is set and a hard gate is raised
    Then the recipients are the site's admins
    When an admin sets the hard gate rule to editors plus the extra address "extra@example.test"
    Then the recipients of a hard gate are "ed@example.test" and "extra@example.test"
    When an admin sets a rule for the automation "ttab" to the address "ruling@example.test"
    Then the recipients of a hard gate from "ttab" are "ruling@example.test"
