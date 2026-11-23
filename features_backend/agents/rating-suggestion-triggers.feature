Feature: The rating agent suggests stars when a Story is published or a Reference is accepted
  The rating agent does not wait for its daily run to look at a new Story. When a Story's page goes live, the Item change feed hears the Story enter the
  published stage and wakes the rating agent; because the agent is paid, the wake gate holds the wake on one timer until the Story has been quiet for the
  site's window, so a burst of edits right after a publish starts one run. When a Reference is accepted, the change feed of the References wakes the agent
  at once for the Stories based on that Reference: a suggestion sits beside a Story's rating, and a Reference is given none. The wake only names its
  subject. The run reads each Story as it is when it starts and judges only a published Story nobody has rated and nobody has suggested stars for.

  A machine never writes a rating, at any rung. At the rung propose the agent writes its suggestion beside the rating (three or four stars, or five for a
  five-star candidate a person decides) and adds the Story to the day's one soft review. A later wake that day adds its Story to that review instead of
  raising a second one. A Story a person rated before the wake is skipped and listed with the reason, and the person's rating stands.

  Background:
    Given a site backend with the published procedure "rate_items"
    And the automation "rate" runs that procedure
    And the automation is adopted as "rate"
    And the policy sets "rate" to "propose"
    And the owner has set the quiet window to 30 minutes after an agent and 5 minutes after a person
    And the site's change feeds wake agents by the engine's core definitions

  Scenario: A publish wakes the agent once the Story is quiet, and the Story gets a suggestion
    Given the site has the typeset Story "story-a" titled "A measured look at evals", which the model would give 4 stars
    When a person publishes "story-a" at "2026-11-21T09:00:00Z"
    Then the gate queue holds 0 wakes for the agent "rate"
    And the pending wait for "rate" on "story-a" is due at "2026-11-21T09:05:00Z"
    When the clock reaches "2026-11-21T09:05:00Z"
    Then the wake for "rate" names the Story "story-a" and no version
    When the rating agent takes its wake
    Then the run ran for the wake "story_published"
    And the run list shows "✓ Did it (suggested)"
    And the run record stores the gate's answer "allowed" for "ratings_suggest" needing the rung "propose"
    And the model was asked about 1 Story
    And "story-a" has the suggestion 4 stars by "agent:rate" from the run, and no rating
    And no rating was written
    And the site has one review request, a soft review "1 rating suggested, 0 five-star candidates"

  Scenario: A five from the model stays a candidate for a person
    Given the site has the typeset Story "story-c" titled "A landmark investigation", which the model would give 5 stars
    When a person publishes "story-c" at "2026-11-21T09:00:00Z"
    And the clock reaches "2026-11-21T09:05:00Z"
    And the rating agent takes its wake
    Then the run lists "story-c" as a five-star candidate for a person
    And "story-c" has the suggestion 5 stars by "agent:rate" from the run, and no rating
    And no rating was written

  Scenario: A Story a person rated before the wake gets no suggestion
    Given the site has the typeset Story "story-b" titled "A routine release note", which the model would give 3 stars
    When a person publishes "story-b" at "2026-11-21T09:00:00Z"
    And a person rates "story-b" 4 stars at "2026-11-21T09:02:00Z"
    And the clock reaches "2026-11-21T09:07:00Z"
    And the rating agent takes its wake
    Then the run list shows "– Nothing to do (nothing_unrated)"
    And the run lists "story-b" as skipped because "already_rated"
    And the model was asked about 0 Stories
    And "story-b" has no suggestion
    And the person's rating of "story-b" is still 4 stars
    And the site has no review request

  Scenario: The day's review gains the Story instead of a second review being raised
    Given the day's review already lists "story-z" with 4 stars suggested
    And the site has the typeset Story "story-a" titled "A routine release note", which the model would give 3 stars
    When a person publishes "story-a" at "2026-11-21T09:00:00Z"
    And the clock reaches "2026-11-21T09:05:00Z"
    And the rating agent takes its wake
    Then the site has one review request, a soft review "2 ratings suggested, 0 five-star candidates"
    And the review links "story-z" and "story-a"

  Scenario: An accepted Reference wakes the agent at once for the Stories based on it
    Given the site has the published Story "story-d" titled "What the new benchmark measures" based on the Reference "ref-1", which the model would give 4 stars
    And the site has the published Story "story-e" a person rated 3 stars, based on the Reference "ref-1"
    When the Reference "ref-1" is accepted by a person at "2026-11-21T10:00:00Z"
    And the rating agent takes its wake
    Then the run ran for the wake "reference_accepted"
    And the Stories based on "ref-1" were read by the relation index
    And the model was asked about 1 Story
    And "story-d" has the suggestion 4 stars by "agent:rate" from the run, and no rating
    And the run lists "story-e" as skipped because "already_rated"
    And the person's rating of "story-e" is still 3 stars
    And no rating was written
