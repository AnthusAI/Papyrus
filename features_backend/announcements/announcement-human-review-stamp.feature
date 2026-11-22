Feature: A human review stamp is a person's review of the Story's current version
  A publication may announce only Stories a person has reviewed. The human review stamp is read from the checklist of the lineage being announced: its
  review step ("Reviewed for readers", review_people; a translation's own human_review) is done against the lineage's CURRENT version, by a person, or by
  an agent on a person's recorded instruction (the person and their words; the stamp is then delegated and names the person). An agent alone cannot close
  the step at all (story-review-stamp.feature), and a mark an agent left with no instruction is no stamp. A later edit makes a new version, and the new
  version has no stamp until the step is done again, so a waiting Announcement returns to waiting. The rule that uses the stamp (requireReviewedSource)
  is specified in announcement-review-policy.feature.

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

  Scenario: An agent's mark with no person's instruction is no stamp
    Given an agent has marked the review step done on version 3 of the Story "slow-water"
    Then the Story "slow-water" at version 3 has no human review stamp
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "has not been reviewed by a person"

  Scenario: An agent's mark on a person's recorded instruction is a delegated stamp
    Given an agent on the instruction of "ellie" has marked the review step done on version 3 of the Story "slow-water"
    Then the Story "slow-water" at version 3 has a human review stamp

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

  Scenario: An unreviewed Story is held in plain words, with no provisional label
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "slow-water version 3 has not been reviewed by a person"
