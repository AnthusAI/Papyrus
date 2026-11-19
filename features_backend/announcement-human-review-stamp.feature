Feature: PROVISIONAL: a human review stamp is a person's mark on the Story's current version
  PROVISIONAL DEFINITION: Ryan has not confirmed it. A publication may announce only Stories a person has reviewed, and no human review stamp existed as data, so it is
  defined here as one fact that is read from the Story's checklist: the step "Reviewed for readers" (review_people) is marked done by a person, which means an actor of
  kind person and never an agent or the system, against the Story's CURRENT version. A later edit makes a new version, and the new version has no stamp until a person
  marks the step again, so a waiting Announcement returns to waiting. When Ryan confirms or changes this definition, only this reader and these scenarios change. The rule
  that uses the stamp (requireReviewedSource) is specified in announcement-review-policy.feature.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And a publication whose announcement review is "soft"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"

  Scenario: A Story nobody has marked has no stamp
    Then the Story "slow-water" at version 3 has no human review stamp

  Scenario: A person marking the review step done stamps the version they reviewed
    When a person reviews version 3 of the Story "slow-water"
    Then the Story "slow-water" at version 3 has a human review stamp

  Scenario: An agent marking the review step done is no stamp
    Given an agent has marked the review step done on version 3 of the Story "slow-water"
    Then the Story "slow-water" at version 3 has no human review stamp
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "has not been reviewed by a person"

  Scenario: A review step a person opened again is no stamp
    Given a person has reviewed version 3 of the Story "slow-water"
    And a person has opened the review step again on version 3 of the Story "slow-water"
    Then the Story "slow-water" at version 3 has no human review stamp

  Scenario: A later edit loses the stamp until a person marks the step again
    Given a person has reviewed version 3 of the Story "slow-water"
    When the Story "slow-water" is edited to version 4 without an Announcement
    Then the Story "slow-water" at version 3 has a human review stamp
    And the Story "slow-water" at version 4 has no human review stamp
    When a person reviews version 4 of the Story "slow-water"
    Then the Story "slow-water" at version 4 has a human review stamp

  Scenario: Every place that shows the rule says the definition is provisional
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "PROVISIONAL"
