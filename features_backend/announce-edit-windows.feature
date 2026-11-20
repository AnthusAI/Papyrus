Feature: The announce agent gives each Delivery its release and lock times from the site's edit windows
  A Delivery is a draft with an edit window, not a one-shot: the window runs from the Delivery's creation to its release time, and the Delivery locks for the send job a lead
  time before that. Neither length is in the code. They are the editWindows of the site's announcement settings, one entry for each kind of Announcement and channel, and the
  narrowest entry that fits wins. When the announce agent makes an Announcement it applies them to the Delivery of each channel, so a story post on X may have twenty minutes
  and an email alert for the same Story an hour, and the Announcement is released at the earliest of them. Where no entry fits, the Delivery is released as soon as it is
  allowed and has no separate lock. This is the wiring of the windows into where the agent builds its Deliveries; the windows themselves, and what a lock does, are specified in
  delivery-edit-window.feature and delivery-lock-and-unlock.feature.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars, in Dry run

  Scenario: An X Delivery is released after its window and locks its lead before that
    Given the edit window for story_published on x is 20 minutes with a lock lead of 5 minutes
    When a 5-star Article is published
    Then the X Delivery is released at "2026-11-13T09:20:00Z" and locks at "2026-11-13T09:15:00Z"
    And the Announcement is released at "2026-11-13T09:20:00Z"

  Scenario: With no window the Delivery is released as soon as it is allowed
    When a 5-star Article is published
    Then the X Delivery is released at "2026-11-13T09:00:00Z" and locks at "2026-11-13T09:00:00Z"

  Scenario: The narrowest entry wins
    Given the edit window for the kind story_published is 60 minutes with a lock lead of 10 minutes
    And the edit window for story_published on x is 20 minutes with a lock lead of 5 minutes
    When a 5-star Article is published
    Then the X Delivery is released at "2026-11-13T09:20:00Z" and locks at "2026-11-13T09:15:00Z"

  Scenario: An X Delivery made after a later rating has a window counted from then
    Given the edit window for story_published on x is 20 minutes with a lock lead of 5 minutes
    And a published 4-star Article that the announce agent already looked at
    When the clock reads "2026-11-13T12:00:00Z"
    And an editor rates the Article 5 stars
    And the announce agent wakes for the Article
    Then the X Delivery is released at "2026-11-13T12:20:00Z" and locks at "2026-11-13T12:15:00Z"
