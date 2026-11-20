Feature: An Announcement is released on time and each Delivery waits for its own approval
  An Announcement is released when its time comes: that is all release means for the Announcement. Whether a Delivery may then go is the Delivery's own
  approval (docs/announcement-records.md): approval "none" goes at once, because the publication's policy approved that version; "hard" waits for a person
  to approve that exact version; "soft" goes when a person approved it, or when the lock time has come with nobody having stopped it. A newer version of the
  Story after an approval returns the Delivery to waiting, because an approval names one version. A planned Announcement can be cancelled before its release,
  and a release time already in the past releases now.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: Approval none releases at once and says the policy did it
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | policy                    |
      | email   | site-one | none     | publication default       |
    When the schedule releases what is due at "2026-11-16T14:00:00Z"
    Then the Announcement "story-published:slow-water" is released
    And the Delivery "email" "site-one" may go at "2026-11-16T14:00:00Z"
    And the Delivery "email" "site-one" was approved by "system" under "publication default"

  Scenario: A hard gate waits for a person
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    When the schedule releases what is due at "2026-11-16T14:00:00Z"
    Then the Announcement "story-published:slow-water" is released
    And the Delivery "email" "site-one" may not go at "2026-11-16T14:00:00Z" because "waiting for approval"
    When the person "ellie" approves version 1 of the Delivery "email" "site-one"
    Then the Delivery "email" "site-one" may go at "2026-11-16T14:00:00Z"
    And the Delivery "email" "site-one" was approved by "ellie"

  Scenario: An approval names one version
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    When the person "ellie" approves version 2 of the Delivery "email" "site-one"
    Then the call is refused saying "names one version"
    And the Delivery "email" "site-one" is not approved

  Scenario: A newer Story version after approval returns a hard gate to waiting
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    And the person "ellie" approves version 1 of the Delivery "email" "site-one"
    When the Story "slow-water" changes to version 4
    Then the Delivery "email" "site-one" is at version 2 and is a draft
    And the Delivery "email" "site-one" is not approved
    And the Announcement is linked to the Story "slow-water" at version 4
    And the Delivery "email" "site-one" may not go at "2026-11-16T14:00:00Z" because "the words are not ready"
    When the Delivery "email" "site-one" is drafted again and ready
    Then the Delivery "email" "site-one" may not go at "2026-11-16T14:00:00Z" because "waiting for approval"

  Scenario: A newer Story version under approval none is approved again by the policy
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the Story "slow-water" changes to version 4
    And the Delivery "email" "site-one" is drafted again and ready
    Then the Delivery "email" "site-one" is at version 2 and is ready
    And the Delivery "email" "site-one" was approved by "system"
    And the Delivery "email" "site-one" may go at "2026-11-16T14:00:00Z"

  Scenario: Soft review lets it go at the lock time when nobody stopped it
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-16T14:00:00Z" and these Deliveries
      | channel | account  | approval | lock at              |
      | email   | site-one | soft     | 2026-11-16T15:00:00Z |
    Then the Delivery "email" "site-one" may not go at "2026-11-16T14:30:00Z" because "waiting for review until the lock time"
    And the Delivery "email" "site-one" may go at "2026-11-16T15:00:00Z"

  Scenario: A Delivery does not go before its release time
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the Delivery "email" "site-one" may not go at "2026-11-16T14:00:00Z" because "waiting for its release time"
    When the schedule releases what is due at "2026-11-16T14:00:00Z"
    Then the Announcement "story-published:slow-water" is planned
    When the schedule releases what is due at "2026-11-17T09:00:00Z"
    Then the Announcement "story-published:slow-water" is released

  Scenario: A release time in the past releases now
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-15T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the schedule releases what is due at "2026-11-16T14:00:00Z"
    Then the Announcement "story-published:slow-water" is released
    And the schedule found it through the planned-by-release-time index

  Scenario: Cancel before release withdraws what was never sent
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the person "ellie" cancels the Announcement "story-published:slow-water"
    Then the Announcement "story-published:slow-water" is cancelled
    And the Delivery "email" "site-one" is withdrawn
    When the schedule releases what is due at "2026-11-18T09:00:00Z"
    Then the Announcement "story-published:slow-water" is cancelled

  Scenario: A released Announcement is not cancelled
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    And the schedule releases what is due at "2026-11-16T14:00:00Z"
    When the person "ellie" cancels the Announcement "story-published:slow-water"
    Then the call is refused saying "only a planned Announcement"

  Scenario: The history only grows
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    When the schedule releases what is due at "2026-11-16T14:00:00Z"
    Then the Announcement "story-published:slow-water" history reads
      | by       | state    | note                       |
      | pipeline | planned  | decided: story_published   |
      | schedule | released | released                   |
