Feature: The three-star floor and the rule that a machine never supplies a five hold under every review policy
  Review is a setting, and no setting lowers these two floors. A Story with no rating or under three stars is never announced, and a rating of five counts only when a person
  gave it: a machine's five is never a reason to announce. This holds for a publication that is fully automatic, one that lets a person stop a post before its lock time, and one
  that needs a person to release every post, and it holds when the publication also requires a review of the source.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"

  Scenario Outline: An unrated Story is never announced, under any review
    Given a publication whose announcement review is "<review>"
    And the Story "slow-water" at version 3 is unrated
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "is unrated; nothing under three stars is announced"

    Examples:
      | review |
      | none   |
      | soft   |
      | hard   |

  Scenario Outline: A Story under three stars is never announced, under any review
    Given a publication whose announcement review is "<review>"
    And the Story "slow-water" at version 3 has 2 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "has 2 stars; nothing under three stars is announced"

    Examples:
      | review |
      | none   |
      | soft   |
      | hard   |

  Scenario Outline: A five that a machine gave is never announced, under any review
    Given a publication whose announcement review is "<review>"
    And the Story "slow-water" at version 3 has 5 stars given by "<machine>"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "a machine never supplies a five"

    Examples:
      | review | machine       |
      | none   | agent:rating  |
      | soft   | agent:rating  |
      | hard   | agent:rating  |
      | none   | automation:x  |
      | soft   |               |

  Scenario Outline: A three-star Story and a five a person gave are announced under every review
    Given a publication whose announcement review is "<review>"
    And the Story "slow-water" at version 3 has <stars> stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then an Announcement was made with 1 Deliveries
    And the Delivery "x" "handle-1" has the review "<review>" from "publication policy"

    Examples:
      | review | stars |
      | none   | 3     |
      | soft   | 3     |
      | hard   | 3     |
      | none   | 5     |
      | hard   | 5     |

  Scenario Outline: The floors hold when the publication also announces only reviewed Stories
    Given a publication whose announcement review is "<review>"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 3 has 2 stars given by "ellie"
    And a person has reviewed version 3 of the Story "slow-water"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "nothing under three stars is announced"

    Examples:
      | review |
      | none   |
      | soft   |
      | hard   |

  Scenario: A roundup is not announced when any Story in it is under the floor
    Given a publication whose announcement review is "none"
    And the Story "good-one" at version 1 has 4 stars given by "ellie"
    And the Story "weak-one" at version 1 has 2 stars given by "ellie"
    When the announce agent announces the Stories "good-one, weak-one" as "roundup" under the key "roundup:weekly:2026-47" on these channels
      | channel | account |
      | email   | weekly  |
    Then nothing was announced because "weak-one has 2 stars"
