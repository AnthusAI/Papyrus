Feature: Kill switches stop work before the next run or send, and resuming loses nothing
  Three switches, each one operation: pause one agent, pause every agent on the site, and pause sending on one channel account. The runner checks a pause at
  the start of every run and the sender at the start of every attempt, so each switch stops the next one. A stopped run is recorded as nothing to do; a
  stopped send waits, it does not fail.

  Resuming never replays a timer's skipped ticks. For each agent woken by changes, each subject whose latest wake the pause stopped gets that wake once more,
  found through the run index by agent from when the pause began, never by reading a table. Two stopped wakes for one subject send one, and the key of each
  wake sent again makes a repeat harmless.

  Scenario: Pausing one agent stops its next run, and no other agent's
    Given a site whose announce agent drafts at the rung "prepare"
    And the rating agent suggests at the rung "propose"
    And Ada paused "announce" in the newsroom because "Checking the X drafts"
    When Story "story-1" goes live
    And the site's wake queue is delivered
    Then the announce agent drafted nothing
    And the rating agent ran for "story-1" 1 time

  Scenario: Pausing the site stops every agent
    Given a site whose announce agent drafts at the rung "prepare"
    And the rating agent suggests at the rung "propose"
    And Ada paused the whole site in the newsroom because "Incident review"
    When Story "story-1" goes live
    And the site's wake queue is delivered
    Then the announce agent drafted nothing
    And the rating agent ran for "story-1" 0 times
    And the stopped run for "story-1" says "The site is paused: Incident review"

  Scenario: Pausing a channel stops the next attempt, and the Delivery waits
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On
    When the owner pauses announcements
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Blocked: paused"
    And nothing was posted

  Scenario: Resuming the site sends each stopped subject once and never a skipped tick
    Given a site whose announce agent drafts at the rung "prepare"
    And the rating agent suggests at the rung "propose"
    And Ada paused the whole site in the newsroom because "Incident review"
    And Story "story-1" is rated 4 stars
    And Story "story-1" is rated 5 stars
    And Story "story-2" goes live
    And the rating agent's daily timer fires
    And the site's wake queue is delivered
    When Ada resumes the whole site in the newsroom because "Incident closed"
    And the site's wake queue is delivered
    And the same wakes are delivered again
    Then the announce agent drafted for "story-1" 1 time
    And the announce agent drafted for "story-2" 1 time
    And the rating agent ran for "story-2" 1 time
    And the rating agent's skipped tick did not run

  Scenario: Work that arrived after the resume is not caught up twice
    Given a site whose announce agent drafts at the rung "prepare"
    And Ada paused "announce" in the newsroom because "Checking the X drafts"
    And Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    When Ada resumes "announce" in the newsroom because "Drafts checked"
    And Story "story-1" is rated 5 stars
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-1" 2 times
    When Ada paused "announce" in the newsroom because "Again"
    And Ada resumes "announce" in the newsroom because "Done"
    Then the resume caught up nothing

  Scenario: Resuming an agent while the site is paused waits for the site
    Given a site whose announce agent drafts at the rung "prepare"
    And Ada paused the whole site in the newsroom because "Incident review"
    And Ada paused "announce" in the newsroom because "Checking the X drafts"
    And Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    When Ada resumes "announce" in the newsroom because "Drafts checked"
    Then the resume caught up nothing and says "The site is still paused"
    When Ada resumes the whole site in the newsroom because "Incident closed"
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-1" 1 time
