Feature: Every wait is a named time on the Delivery
  A Delivery that is waiting says what for and until when, as fields on its row: when it may be released (releaseAt), when it locks for sending (lockAt, equal
  to the release time when there is no separate lock), and when it will be tried again (nextAttemptAt, with waitingFor: rate limit, budget cycle or release).
  dueAt is the earliest of the times still pending, and it is present only while one is, so one sparse index on it lists what is due without reading the table.
  A lock is a fact (lockedAt and lockedVersion), not something held: nothing expires and a person who never answers blocks only that Delivery.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: The due time is the earliest of the lock, the next attempt and the release
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | lock at              |
      | email   | site-one | soft     | 2026-11-17T08:00:00Z |
    Then the Delivery "email" "site-one" is due at "2026-11-17T08:00:00Z"
    When the Delivery "email" "site-one" will be tried again at "2026-11-17T07:00:00Z" waiting for "rate limit"
    Then the Delivery "email" "site-one" is due at "2026-11-17T07:00:00Z"
    And the Delivery row "email" "site-one" holds
      | field         | value                |
      | nextAttemptAt | 2026-11-17T07:00:00Z |
      | waitingFor    | rate limit           |

  Scenario: With no separate lock the lock time equals the release time
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the Delivery row "email" "site-one" holds
      | field     | value                |
      | releaseAt | 2026-11-17T09:00:00Z |
      | lockAt    | 2026-11-17T09:00:00Z |
    And the Delivery "email" "site-one" is due at "2026-11-17T09:00:00Z"

  Scenario: The due index returns what is due and leaves out what waits for nothing
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T13:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    And the decision "story-published:tide-tables" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-20T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the decision "story-published:harbour" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T13:00:00Z" and these Deliveries
      | channel  | account  | approval |
      | linkedin | page-one | none     |
    And the Delivery "linkedin" "page-one" is finished as "sent"
    When the schedule asks what is due at "2026-11-16T14:00:00Z"
    Then it is told about exactly these Deliveries
      | channel | account  |
      | email   | site-one |
    And the Delivery "linkedin" "page-one" has no due time
    And the Delivery "linkedin" "page-one" is not in the due index
    And the due index holds 2 Deliveries

  Scenario: Locking records the version as a fact and the lock time is no longer pending
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | lock at              |
      | email   | site-one | none     | 2026-11-17T08:00:00Z |
    When the Delivery "email" "site-one" is locked
    Then the Delivery row "email" "site-one" holds
      | field         | value                |
      | lockedVersion | 1                    |
      | lockedAt      | 2026-11-16T14:00:00Z |
    And the Delivery "email" "site-one" is due at "2026-11-17T09:00:00Z"

  Scenario: Locking a Delivery that no one approved is refused
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    When the Delivery "email" "site-one" is locked
    Then the call is refused saying "no approved version"

  Scenario: Moving the release time moves the due time
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the release of the Delivery "email" "site-one" moves to "2026-11-18T09:00:00Z"
    Then the Delivery "email" "site-one" is due at "2026-11-18T09:00:00Z"

  Scenario: A wait names one of three reasons
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the Delivery "email" "site-one" will be tried again at "2026-11-17T07:00:00Z" waiting for "a headache"
    Then the call is refused saying "waitingFor is one of"
    When the Delivery "email" "site-one" will be tried again at "2026-11-17T07:00:00Z" waiting for "budget cycle"
    And the Delivery "email" "site-one" stops waiting
    Then the Delivery row "email" "site-one" has no field "nextAttemptAt"
    And the Delivery row "email" "site-one" has no field "waitingFor"
