Feature: At propose the rating agent suggests stars beside a Story's rating, and a person decides
  A machine never writes a rating. At the rung propose the rating agent writes what it would have rated as a suggestion beside the Story's rating:
  three or four stars, or five for a five-star candidate, with who suggested it and the run whose record holds the reason. The rating itself stays
  empty until a person decides. Every suggestion of the day is gathered into one soft review, "N ratings suggested, M five-star candidates", that
  links each Story; a second run on the same day adds to it instead of raising another. A person confirms a suggestion (it becomes that person's
  rating), gives other stars, or leaves it. A Story a person rated is skipped, and a person's rating always wins.

  Background:
    Given a site backend with the published procedure "rate_items"
    And the automation "rate" runs that procedure
    And the automation is adopted as "rate"

  Scenario: A suggestion appears beside the Story and the rating stays empty
    Given the policy sets "rate" to "propose"
    And the site has these published Stories nobody has rated
      | story   | title                    | model says |
      | story-a | A routine release note   | 3          |
      | story-b | A measured look at evals | 4          |
    When the daily wake arrives for the automation
    Then the run list shows "✓ Did it (suggested)"
    And the run record stores the gate's answer "allowed" for "ratings_suggest" needing the rung "propose"
    And "story-a" has the suggestion 3 stars by "agent:rate" from the run, and no rating
    And "story-b" has the suggestion 4 stars by "agent:rate" from the run, and no rating
    And no rating was written

  Scenario: Five-star candidates are listed for a person, never rated
    Given the policy sets "rate" to "propose"
    And the site has these published Stories nobody has rated
      | story   | title                    | model says |
      | story-c | A landmark investigation | 5          |
    When the daily wake arrives for the automation
    Then the run lists "story-c" as a five-star candidate for a person
    And "story-c" has the suggestion 5 stars by "agent:rate" from the run, and no rating
    And no rating was written

  Scenario: The day's suggestions are one grouped soft review
    Given the policy sets "rate" to "propose"
    And the site has these published Stories nobody has rated
      | story   | title                    | model says |
      | story-a | A routine release note   | 3          |
      | story-b | A measured look at evals | 4          |
      | story-c | A landmark investigation | 5          |
    When the daily wake arrives for the automation
    Then the site has one review request, a soft review "2 ratings suggested, 1 five-star candidate"
    And the review links "story-a", "story-b" and "story-c"

  Scenario: A second run on the same day adds to the day's review instead of raising another
    Given the day's review already lists "story-z" with 4 stars suggested
    When the agent raises the day's review for "story-a" at 3 stars and "story-c" at 5 stars
    Then the site has one review request, a soft review "2 ratings suggested, 1 five-star candidate"
    And the review links "story-z", "story-a" and "story-c"

  Scenario: At observe nothing is suggested and no review is raised
    Given the policy sets "rate" to "observe"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the run list shows "✓ Did it (proposed)"
    And "story-a" has no suggestion
    And the site has no review request

  Scenario: A Story a person rated is skipped
    Given the policy sets "rate" to "propose"
    And the site has a published Story "story-e" a person rated 4 stars
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the model was asked about 1 Story
    And "story-e" has no suggestion
    And the person's rating of "story-e" is still 4 stars

  Scenario: A Story with a suggestion waiting is not judged again
    Given the policy sets "rate" to "propose"
    And the site has a published Story "story-s" with 4 stars suggested and no rating
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    When the daily wake arrives for the automation
    Then the model was asked about 1 Story

  Scenario: A Story a person rated while the run was working keeps the person's rating
    Given the policy sets "rate" to "propose"
    And the site has these published Stories nobody has rated
      | story   | title                  | model says |
      | story-a | A routine release note | 3          |
    And a person rates "story-a" 4 stars before the run reaches it
    When the daily wake arrives for the automation
    Then the run lists "story-a" as left alone because "already_rated"
    And the person's rating of "story-a" is still 4 stars

  Scenario: Confirming a suggestion makes it the person's rating
    Given a Story "story-a" with 4 stars suggested by "agent:rate" and no rating
    When a person confirms the suggestion for "story-a"
    Then the person's rating of "story-a" is 4 stars
    And the answer says the suggestion was confirmed unchanged

  Scenario: A person can give other stars instead of the suggestion
    Given a Story "story-a" with 4 stars suggested by "agent:rate" and no rating
    When a person confirms the suggestion for "story-a" with 2 stars instead
    Then the person's rating of "story-a" is 2 stars
    And the answer says the person changed the suggestion from 4 stars

  Scenario: A machine can never write a rating or decide a suggestion, whatever calls the operation
    Given a Story "story-f" nobody has rated and a Story "story-g" a person rated 4 stars
    When an agent asks the operation "ratings_set" for "story-f" at 3 stars
    Then the answer is the error "human_required"
    When an agent asks the operation "ratings_suggest" for "story-g" at 3 stars
    Then the answer is the error "constraint_conflict"
    And the person's rating of "story-g" is still 4 stars
    When an agent asks the operation "ratings_suggest" for "story-f" at 2 stars
    Then the answer is the error "invalid_input"
    And no rating was written
