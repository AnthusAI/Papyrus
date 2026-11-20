Feature: The rating agent looks at unrated published Stories each day and, at observe, only says what it would rate
  The rating agent is the first always-on agent (slice L1, PPY-d85860). Once a day its schedule puts a wake on the site's queue and the procedure runner
  takes it. The agent reads the published Stories that nobody has rated, by the site's head stage index, newest first, and for each asks the bulk-tier
  model one question: three stars (the default), four (clearly better than the usual Story), or five (a candidate for a person). A five is never a
  rating: the run lists it as a candidate and nothing more. A person's rating is never touched, and a Story a person rated is never listed.

  What the agent may do is the site's agent policy, not its code. The run asks the one gate whether it may write a rating (the operation "ratings_set",
  which the operation table lets an agent call from the rung draft). At the rung observe the gate says a person would have to do it, so the run
  records what it would rate and why, writes no rating and files no review request. Raising the rung to draft is a change of the policy document
  and changes no code: the same run then writes the threes and fours through the same gate, and still never a five.

  Every scenario goes through the procedure runner's own entry point with the real procedure file, the site's real policy document and run records.
  Only the places the world is reached are stood in for: the site's Story index, the guidelines read, the rating write and the model.

  Background:
    Given a site backend with the published procedure "rate_items"
    And the automation "rate" runs that procedure
    And the automation is adopted as "rate"

  Scenario: At observe the run lists what it would rate and writes nothing
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story  | title                        | model says |
      | story-a | A routine release note       | 3          |
      | story-b | A measured look at evals     | 4          |
    When the daily wake arrives for the automation
    Then the run list shows "✓ Did it (proposed)"
    And the run proposes 2 ratings: "story-a" at 3 stars and "story-b" at 4 stars
    And every proposal has a reason
    And no rating was written
    And the run record counts 2 looked at and 0 written
    And the Story index was read only as the published head partition
    And the run record names the responsibility "rate", policy version 1 and the rung "observe"

  Scenario: At observe the gate is asked and says a person would have to write the rating, and no review request is filed
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story  | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run record stores the gate's answer "human_required" for "ratings_set" needing the rung "draft"
    And no review request is filed
    And no rating was written

  Scenario: A five from the model is listed as a candidate for a person and is never proposed
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                       | model says |
      | story-a | A routine release note      | 3          |
      | story-c | A landmark investigation    | 5          |
    When the daily wake arrives for the automation
    Then the run list shows "✓ Did it (proposed)"
    And the run proposes 1 rating: "story-a" at 3 stars
    And the run lists "story-c" as a five-star candidate for a person
    And no proposal in the run is for 5 stars
    And no rating was written

  Scenario: An answer that is not three, four or five is listed as unjudged and never becomes a rating
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
      | story-d | A thin announcement    | 2          |
    When the daily wake arrives for the automation
    Then the run proposes 1 rating: "story-a" at 3 stars
    And the run lists "story-d" as unjudged because "model_answer_invalid"

  Scenario: A Story a person rated is never looked at
    Given the policy sets "rate" to "observe"
    And the site has a published Story "story-e" a person rated 4 stars
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run proposes 1 rating: "story-a" at 3 stars
    And the model was asked about 1 Story
    And the run record counts 1 looked at and 0 written

  Scenario: A translation is judged through its source and is not listed on its own
    Given the policy sets "rate" to "observe"
    And the site has a published translation "story-a--es" of the Story "story-a"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run proposes 1 rating: "story-a" at 3 stars
    And the model was asked about 1 Story

  Scenario: A day with nothing unrated ends nothing, with the reason
    Given the policy sets "rate" to "observe"
    And the site has a published Story "story-e" a person rated 4 stars
    When the daily wake arrives for the automation
    Then the run list shows "– Nothing to do (nothing_unrated)"
    And the model was asked about 0 Stories
    And no rating was written

  Scenario: The site's writing guidelines are read through the gate and given to the model
    Given the policy sets "rate" to "observe"
    And the site's writing guidelines say "Plain words. Say what is known."
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run record stores the gate's answer "allowed" for "guidelines_resolve"
    And the model was given the guidelines "Plain words. Say what is known."

  Scenario: At draft the same run writes the threes and fours through the gate and still never a five
    Given the policy sets "rate" to "draft"
    And the site has these published Stories nobody has rated
      | story   | title                    | model says |
      | story-a | A routine release note   | 3          |
      | story-b | A measured look at evals | 4          |
      | story-c | A landmark investigation | 5          |
    When the daily wake arrives for the automation
    Then the run list shows "✓ Did it (rated)"
    And the run record stores the gate's answer "allowed" for "ratings_set" needing the rung "draft"
    And the ratings written are "story-a" at 3 stars and "story-b" at 4 stars, each by "agent:rate"
    And the run lists "story-c" as a five-star candidate for a person
    And no rating of 5 was written

  Scenario: A Story a person rated while the run was working is left alone
    Given the policy sets "rate" to "draft"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    And a person rates "story-a" 4 stars before the run reaches it
    When the daily wake arrives for the automation
    Then the run lists "story-a" as left alone because "already_rated"
    And the person's rating of "story-a" is still 4 stars

  Scenario: An agent can never write a five or replace a rating, whatever calls the operation
    Given a Story "story-f" nobody has rated and a Story "story-g" a person rated 4 stars
    When an agent asks the operation "ratings_set" for "story-f" at 5 stars
    Then the answer is the error "invalid_input"
    When an agent asks the operation "ratings_set" for "story-g" at 3 stars
    Then the answer is the error "constraint_conflict"
    And the person's rating of "story-g" is still 4 stars

  Scenario: A run that is out of time stops between Stories and says so
    Given the policy sets "rate" to "observe"
    And each model call takes 40 seconds and the run has 100 seconds left
    And the site has these published Stories nobody has rated
      | story   | title        | model says |
      | story-a | First story  | 3          |
      | story-b | Second story | 3          |
      | story-c | Third story  | 3          |
      | story-d | Fourth story | 3          |
    When the daily wake arrives for the automation
    Then the run proposes 2 ratings: "story-a" at 3 stars and "story-b" at 3 stars
    And the run record says it stopped because "deadline"
    And the model was asked about 2 Stories

  Scenario: A model that fails for every Story fails the run and rates nothing
    Given the policy sets "rate" to "draft"
    And the model service fails every call
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run list shows "✗ Failed (procedure_error)"
    And no rating was written

  Scenario: One Story the model fails on is listed and the rest are still judged
    Given the policy sets "rate" to "observe"
    And the model service fails for "story-b"
    And the site has these published Stories nobody has rated
      | story   | title                    | model says |
      | story-a | A routine release note   | 3          |
      | story-b | A measured look at evals | 4          |
    When the daily wake arrives for the automation
    Then the run proposes 1 rating: "story-a" at 3 stars
    And the run lists "story-b" as failed because "model_failed"

  Scenario: A site whose head stage index cannot be read fails the run and says so instead of scanning
    Given the policy sets "rate" to "observe"
    And the site has no head stage index
    When the daily wake arrives for the automation
    Then the run list shows "✗ Failed (procedure_error)"
    And the run's error says "head stage index"
    And no rating was written

  Scenario: The model is paid for and the run says what it cost
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run record carries the usage of 1 model call by "gpt-6-luna"

  Scenario: An agent nobody adopted starts nothing and the model is never called
    Given the automation is not adopted
    And the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run list shows "– Nothing to do (not_adopted)"
    And the model was asked about 0 Stories
    And the Story index was not read

  Scenario: A rating agent whose rung is off starts nothing
    Given the policy sets "rate" to "off"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run list shows "– Nothing to do (rung_off)"
    And the model was asked about 0 Stories
    And the Story index was not read

  Scenario: A paused rating agent starts nothing and says why
    Given the policy sets "rate" to "observe"
    And an admin paused "rate" because "Checking the first proposals"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run list shows "– Nothing to do (paused)"
    And the model was asked about 0 Stories
    And the Story index was not read

  Scenario: A second wake with the same wake key does not run twice
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives twice with the same wake key
    Then the second answer is a duplicate of the first run
    And the model was asked about 1 Story
    And the site holds one run record for that wake key
