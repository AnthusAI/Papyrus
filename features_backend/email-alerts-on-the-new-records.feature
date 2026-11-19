Feature: An email alert is the email Delivery of a Story's Announcement
  An alert is the message every reader of an every-item list gets when a Story goes live or newly reaches the list's rating bar. It is no longer a separate model
  with its own once-only rows and its own issue. The announce agent decides once for the Story: one Announcement whose once-only key is the Story's, and one email
  Delivery whose audience is every every-item list that carries the Story. The alert's Markus body (the title as a link, the dek, the first paragraph of prose and
  a "Read it" link) is the Delivery's words, a file in S3 and never a catalog row. The first attempt of that Delivery is one Caducus story.published event, so the
  fan-out, the suppression checks and the record of each reader are Caducus's, and the Delivery holds only counts that match Caducus's own records. A reader who is
  on two of the lists gets one message. Nothing under three stars is alerted, whatever a list asks for, and a person's five stars is never needed.

  The alert rows kept from before (one row for each list and Story, which stopped a second alert) are converted by a command that changes keys only: each Story's rows
  become one Announcement with a sent email Delivery, so the announce agent finds it and alerts nobody twice. Running the command again changes nothing. An alarm to
  the operators is not an editorial decision, so it is never an Announcement: it stays a plain Caducus event. Nothing here sends a real email: Caducus runs in memory
  with its mailer replaced by a recorder, and every address is a placeholder.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And a site "alpha" with the lists "stories" (every story) and "security" (the security section)
    And the every-item lists "stories" and "security" are carried by the announce agent

  Scenario: A Story going live makes one Announcement and one email Delivery whose words are the alert body
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    Then the catalog holds 1 Announcements and 1 Deliveries
    And the Delivery of "story-published:slow-water" is "ready"
    And the email Delivery of "story-published:slow-water" is for the lists "security, stories"
    And the words of the email Delivery of "story-published:slow-water" begin "## [Slow water rises](https://alpha.example.test/security/slow-water.html)"
    And the words of the email Delivery of "story-published:slow-water" say "Read it on alpha.example.test"
    And the Delivery's row holds no address and no words of the message

  Scenario: A Story under the three-star floor is not alerted, whatever a list asks for
    When the announce agent decides for the Story "slow-water" in the "security" section rated 2 stars
    Then the catalog holds no Announcement

  Scenario: A rating that makes a Story qualify later is the same decision, made once
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    And the announce agent decides for the Story "slow-water" in the "security" section rated 5 stars
    Then the catalog holds 1 Announcements and 1 Deliveries
    And the announce agent's last decision was "already decided for this Story"

  Scenario: The first attempt is one story.published event and the counts match Caducus, with a reader on two lists getting one message
    Given "reader1@example.test" confirmed "stories"
    And "reader2@example.test" confirmed "stories" and "security"
    And "reader3@example.test" confirmed "security"
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    And the worker sends the alert of "story-published:slow-water" and Caducus works through its queue
    Then the first attempt of the email Delivery of "story-published:slow-water" is the Caducus event "story.published" for the Delivery
    And the Delivery of "story-published:slow-water" counts "3 sent"
    And Caducus's log for the Delivery of "story-published:slow-water" holds 3 readers: "sent 3"
    And "reader2@example.test" received 1 message
    And each message says "Slow water rises" and links to "https://alpha.example.test/security/slow-water.html"

  Scenario: The deliver step hands every due email Delivery to Caducus, and a site without an email channel hands over nothing
    Given "reader1@example.test" confirmed "stories"
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    And the deliver step runs for a site without an email channel
    Then the Delivery of "story-published:slow-water" is "ready"
    When the Announcement "story-published:slow-water" is released
    And the deliver step runs with Caducus's email channel and Caducus works through its queue
    Then the first attempt of the email Delivery of "story-published:slow-water" is the Caducus event "story.published" for the Delivery
    And "reader1@example.test" received 1 message

  Scenario: Kept alert rows still prevent a second alert after conversion
    Given the newsletter table kept these alert rows
      | list     | story      | issue | issue status |
      | stories  | slow-water | a1    | sent         |
      | security | slow-water | a2    | sent         |
      | stories  | old-news   | a3    | sent         |
    When the kept alert rows are converted
    Then the catalog holds 2 Announcements and 2 Deliveries
    And the Delivery of "story-published:slow-water" is "sent"
    And the email Delivery of "story-published:slow-water" is for the lists "security, stories"
    And the words of the email Delivery of "story-published:slow-water" begin "## [Slow water rises]"
    And the Announcement "story-published:slow-water" is released
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    Then the announce agent's last decision was "already decided for this Story"
    And the catalog holds 2 Announcements and 2 Deliveries
    And the worker sends nothing for "story-published:slow-water"
    And nobody is mailed

  Scenario: The conversion command is idempotent
    Given the newsletter table kept these alert rows
      | list     | story      | issue | issue status |
      | stories  | slow-water | a1    | sent         |
      | security | slow-water | a2    | sent         |
    When the kept alert rows are converted
    And the kept alert rows are converted
    Then the conversion's second run made 0 Announcements and found 1 already converted
    And the catalog holds 1 Announcements and 1 Deliveries
    And the Delivery of "story-published:slow-water" has 1 attempt

  Scenario: A kept row whose alert never went is decided and not alerted now
    Given the newsletter table kept these alert rows
      | list    | story      | issue | issue status      |
      | stories | slow-water | a1    | awaiting_approval |
    When the kept alert rows are converted
    Then the Delivery of "story-published:slow-water" is "withdrawn"
    When the announce agent decides for the Story "slow-water" in the "security" section rated 4 stars
    Then the announce agent's last decision was "already decided for this Story"

  Scenario: The plan names each Story once with the lists that kept a row, and writes nothing
    Given the newsletter table kept these alert rows
      | list     | story      | issue | issue status |
      | stories  | slow-water | a1    | sent         |
      | security | slow-water | a2    | sent         |
    Then the conversion plan names "slow-water" for the lists "security, stories"
    And the catalog holds no Announcement

  Scenario: An alarm to the operators is not an Announcement
    Then Announcements have once-only keys only for a published Story, a roundup and a correction
    And the operator listener's stack does not name the Announcement or Delivery records
