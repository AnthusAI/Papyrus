Feature: A Story and the Announcements list show each Delivery in words and marks
  One Announcement is the decision to say something, and each channel's version of it is a Delivery. The Story's drawer shows where the Story was announced as one line
  for each Delivery, read through the "announces" relation from the Story's side: one indexed query for the relation, then one Announcement and one Deliveries query for each.
  The Announcements list shows the same lines newest first, from the planned-by-release-time index. Every line says its state, its review and what needs a person in
  words, with a Lucide icon beside the words, so no line depends on colour. A Delivery that is due and has no attempt says "Overdue". A Delivery with an attempt that has
  no answer says "Outcome unknown" until Caducus's record settles it, and no clock decides. A blocked draft shows one open review flag for its Announcement, however many
  channels are blocked. Nothing here lists a table, opens a subscription or writes a row.

  Background:
    Given an empty announcement catalog that knows its Stories
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the Story "slow-water" has the title "Slow water" at version 3

  # --- where a Story was announced ----------------------------------------------------------------------------------------------------------------

  Scenario: A Story shows one line for each Delivery under one decision
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
      | email   | site-one | soft     |
    When the Story "slow-water" is read through the door for where it was announced
    Then the answer holds 1 Announcement
    And the line for "email" "site-one" reads "Ready" with the mark "calendar-check"
    And the line for "x" "handle-1" reads "Ready" with the mark "calendar-check"
    And the door read the index "semanticRelationsByObjectState" once
    And every read was an index query or a get by id
    And the question wrote nothing

  Scenario: A Story that was never announced answers with nothing
    When the Story "slow-water" is read through the door for where it was announced
    Then the answer holds 0 Announcements

  Scenario: A correction shows only the live Delivery
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    When the Story "slow-water" is read through the door for where it was announced
    Then the answer holds 1 Announcement
    And the line for "x" "handle-1" reads "Ready" with the mark "calendar-check"

  # --- the review, in words and marks ---------------------------------------------------------------------------------------------------------------

  Scenario: Each Delivery says how it is reviewed
    Given a publication whose announcement review is "none"
    And the announcement review for the channel "email" is "hard"
    And the announcement review for the channel "linkedin" is "soft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | x        | handle-1 |
      | email    | site-one |
      | linkedin | page-one |
    And the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" shows the review "Released automatically by publication policy" with the mark "bot"
    And the line for "email" "site-one" shows the review "Waits for a person to release it" with the mark "hand"
    And the line for "linkedin" "page-one" shows the review "Goes at its lock time unless a person stops it" with the mark "hourglass"

  Scenario: A Delivery a person released says so
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    And the person "ellie" approves version 1 of the Delivery "email" "site-one"
    When the Story "slow-water" is read through the door for where it was announced
    Then the line for "email" "site-one" shows the review "Released by a person (ellie)" with the mark "user-check"

  Scenario: A Delivery that will not go shows no review
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | hard     |
    When the person "ellie" cancels the Announcement "story-published:slow-water"
    And the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" reads "Withdrawn" with the mark "undo-2"
    And the line for "x" "handle-1" shows no review

  # --- overdue --------------------------------------------------------------------------------------------------------------------------------------

  Scenario: A due Delivery with no attempt shows "Overdue"
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T08:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" says "Overdue" with the mark "clock-alert"
    When the Announcements list is read through the door
    Then the overdue list holds the Delivery "x" "handle-1"
    And the line for "x" "handle-1" says "Overdue" with the mark "clock-alert"
    And the door read the index "deliveriesByDue" once

  Scenario: A Delivery that is not due yet is not overdue
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T10:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the Announcements list is read through the door
    Then the overdue list holds 0 Deliveries
    And the line for "x" "handle-1" does not say "Overdue"

  Scenario: A Delivery that has had an attempt is waiting, not overdue
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T08:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And one worker serves the channel "x" account "handle-1"
    And the channel answers the next new event with "refused" and "rate limit" until "2026-11-17T09:30:00Z"
    And the worker sends the Delivery "x" "handle-1"
    And the clock reads "2026-11-17T10:00:00Z"
    When the Announcements list is read through the door
    Then the overdue list holds 0 Deliveries
    And the line for "x" "handle-1" does not say "Overdue"
    And the line for "x" "handle-1" shows the last attempt as "Refused" with the mark "✗"

  # --- outcome unknown ------------------------------------------------------------------------------------------------------------------------------

  Scenario: An attempt left started shows "Outcome unknown" until it is settled
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And one worker serves the channel "x" account "handle-1"
    And the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" reads "Sending" with the mark "send"
    And the line for "x" "handle-1" says "Outcome unknown" with the mark "circle-help"
    When Caducus records the post for attempt 1 of the Delivery "x" "handle-1"
    And the worker settles the Delivery "x" "handle-1"
    And the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" reads "Sent" with the mark "circle-check"
    And the line for "x" "handle-1" does not say "Outcome unknown"

  Scenario: An attempt with no record yet stays unknown, whatever the clock says
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And one worker serves the channel "x" account "handle-1"
    And the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    And the clock reads "2026-11-19T09:00:00Z"
    When the Announcements list is read through the door
    Then the line for "x" "handle-1" says "Outcome unknown" with the mark "circle-help"

  # --- a blocked draft asks once --------------------------------------------------------------------------------------------------------------------

  Scenario: A blocked draft shows one review flag for its Announcement, however many channels are blocked
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
      | email   | site-one | soft     |
    When the checks on the draft of "x" "handle-1" fail because "the post is over 280 characters"
    And the checks on the draft of "email" "site-one" fail because "the link is missing"
    And the Story "slow-water" is read through the door for where it was announced
    Then the line for "x" "handle-1" reads "Blocked: check failed" with the mark "ban"
    And the line for "email" "site-one" reads "Blocked: check failed" with the mark "ban"
    And the line for "x" "handle-1" says "The checks on its words failed" with the mark "shield-alert"
    And the answer shows the review flag once
    And exactly 1 review request exists
    And the question wrote nothing

  Scenario: A flag that was answered is no longer shown
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the checks on the draft of "x" "handle-1" fail because "the post is over 280 characters"
    And a person answers the review flag of the Announcement "story-published:slow-water"
    And the Story "slow-water" is read through the door for where it was announced
    Then the answer shows no review flag

  Scenario: A blocked draft is not overdue
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T08:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the checks on the draft of "x" "handle-1" fail because "the post is over 280 characters"
    And the Announcements list is read through the door
    Then the overdue list holds 0 Deliveries
    And the answer shows the review flag once

  # --- the list -------------------------------------------------------------------------------------------------------------------------------------

  Scenario: The list reads Announcements newest first and names each Story
    Given the Story "tide-tables" is at version 1
    And the Story "tide-tables" has the title "Tide tables" at version 1
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-18T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the decision "story-published:tide-tables" of kind "story_published" is made for the Story "tide-tables" with a release time "2026-11-20T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the Announcements list is read through the door
    Then the Announcements come in this order of release
      | release              |
      | 2026-11-20T09:00:00Z |
      | 2026-11-18T09:00:00Z |
    And the Announcement released "2026-11-20T09:00:00Z" is about the Story titled "Tide tables"
    And the Announcement released "2026-11-18T09:00:00Z" is about the Story titled "Slow water"
    And every read was an index query or a get by id
    And the question wrote nothing

  Scenario: A page ends where the release time changes, so Announcements released together are never split
    Given the Story "tide-tables" is at version 1
    And the Story "harbour-lights" is at version 1
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-20T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the decision "story-published:tide-tables" of kind "story_published" is made for the Story "tide-tables" with a release time "2026-11-20T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the decision "story-published:harbour-lights" of kind "story_published" is made for the Story "harbour-lights" with a release time "2026-11-19T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the Announcements list is read through the door in pages of 1
    Then the pages hold these Announcements in turn
      | page | release              |
      | 1    | 2026-11-20T09:00:00Z |
      | 1    | 2026-11-20T09:00:00Z |
      | 2    | 2026-11-19T09:00:00Z |
    And the last page has no next page

  Scenario: An empty list says so and reads only indexes
    When the Announcements list is read through the door
    Then the answer holds 0 Announcements
    And the overdue list holds 0 Deliveries
    And the question wrote nothing

  # --- the console's door ---------------------------------------------------------------------------------------------------------------------------

  Scenario: The console reads a Story's lines through the announcements door
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T08:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
      | email   | site-one | soft     |
    When the console asks the announcements door for where the Story "slow-water" was announced
    Then the answer holds 1 Announcement
    And the line for "x" "handle-1" says "Overdue" with the mark "clock-alert"
    And the line for "email" "site-one" shows the review "Goes at its lock time unless a person stops it" with the mark "hourglass"
    And the question wrote nothing

  Scenario: The console reads the list through the announcements door
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T08:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the console asks the announcements door for the list
    Then the answer holds 1 Announcement
    And the overdue list holds the Delivery "x" "handle-1"
    And the Announcement released "2026-11-17T08:00:00Z" is about the Story titled "Slow water"

  Scenario: Someone who is not an editor or an admin is refused at the door
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When a signed-in reader asks the announcements door for where the Story "slow-water" was announced
    Then the door refuses with "not_authorized"

  Scenario: The door only reads
    When the console asks the announcements door to "announcements_pause"
    Then the door refuses with "invalid_input"
    And the door refusal says "this door only reads"

  Scenario: Each family of operations is run through its own door
    When the console asks the image door for where the Story "slow-water" was announced
    Then the door refuses with "invalid_input"
    And the door refusal says "announcements_where is run through announcementsRead, not imageRead"

  Scenario: What the door reads loads in the image service function, which carries no PyYAML
    Then the read path of the list loads without PyYAML

  # --- the commands ---------------------------------------------------------------------------------------------------------------------------------

  Scenario: The commands are on the command line and in the agents' tools
    Then the command is listed among the announcements commands as "where"
    And the command is listed among the announcements commands as "recent"
    And the command is listed among the announcements commands as "explain"
    And the default announcements commands include a handler for "announcements_where"
    And the default announcements commands include a handler for "announcements_recent"
    And the default announcements commands include a handler for "announcements_explain"
    And the default announcements commands include a handler for "announcements_review_show"
