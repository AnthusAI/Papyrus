Feature: Post spacing on one account
  The owner of a publication may ask for time between one post and the next on one channel account, so a run of announcements does not land as a burst. It is an owner
  setting in the announcement settings, by account, and it is empty by default: an account with no spacing posts as soon as a Delivery is due. When spacing is set, the
  one worker for that account holds the next post until the spacing has passed since the account's last post. The held Delivery keeps its place: it stays ready, says
  that it waits for post spacing, and names the time the spacing ends, and it goes like any other wait once that time has come. Spacing is about the account, so another
  account is never held by it.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the Story "tide-pools" is at version 1
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
      | x       | handle-2 | none     | Other words |
    And the decision "story-published:tide-pools" of kind "story_published" is made for the Story "tide-pools" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text         |
      | x       | handle-1 | none     | Second words |

  Scenario: With no spacing set, the next post goes as soon as it is due
    Given one worker serves the channel "x" account "handle-1"
    When the worker sends the Delivery of "story-published:slow-water" for "x" "handle-1"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the Delivery of "story-published:slow-water" for "x" "handle-1" is "sent"
    And the Delivery of "story-published:tide-pools" for "x" "handle-1" is "sent"

  Scenario: With spacing set, the next post is held until the spacing has passed
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    When the worker sends the Delivery of "story-published:slow-water" for "x" "handle-1"
    And the clock reads "2026-11-17T09:10:00Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the call is refused saying "waiting for post spacing until 2026-11-17T09:30:00Z"
    And the Delivery of "story-published:tide-pools" for "x" "handle-1" is "ready"
    And the Delivery of "story-published:tide-pools" for "x" "handle-1" has 0 attempts
    And the Delivery of "story-published:tide-pools" for "x" "handle-1" is waiting for "post spacing" until "2026-11-17T09:30:00Z"
    And exactly 1 post was made

  Scenario: The held post goes once the spacing has passed
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    When the worker sends the Delivery of "story-published:slow-water" for "x" "handle-1"
    And the clock reads "2026-11-17T09:10:00Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    And the clock reads "2026-11-17T09:29:59Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the call is refused saying "waiting for post spacing"
    When the clock reads "2026-11-17T09:30:00Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the Delivery of "story-published:tide-pools" for "x" "handle-1" is "sent"
    And the Delivery of "story-published:tide-pools" for "x" "handle-1" waits for nothing
    And exactly 2 posts were made

  Scenario: Spacing is measured from the last post, so a later post waits again
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    When the worker sends the Delivery of "story-published:slow-water" for "x" "handle-1"
    And the clock reads "2026-11-17T09:30:00Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the Delivery of "story-published:tide-pools" for "x" "handle-1" is "sent"

  Scenario: Spacing on one account never holds another account
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    And one worker serves the channel "x" account "handle-2" with post spacing of 30 minutes
    When the worker for "x" "handle-1" sends the Delivery "x" "handle-1"
    And the clock reads "2026-11-17T09:05:00Z"
    And the worker for "x" "handle-2" sends the Delivery "x" "handle-2"
    Then the Delivery "x" "handle-2" is "sent"

  Scenario: A post whose outcome is not known yet still holds the next one
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    And an attempt is opened for the Delivery of "story-published:slow-water" for "x" "handle-1" and the worker dies before the call
    When the clock reads "2026-11-17T09:10:00Z"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the call is refused saying "waiting for post spacing"

  Scenario: A post that was refused is not a post, so it does not hold the next one
    Given one worker serves the channel "x" account "handle-1" with post spacing of 30 minutes
    And the channel answers the next new event with "failed" and "duplicate content"
    When the worker sends the Delivery of "story-published:slow-water" for "x" "handle-1"
    And the worker sends the Delivery of "story-published:tide-pools" for "x" "handle-1"
    Then the Delivery of "story-published:tide-pools" for "x" "handle-1" is "sent"
