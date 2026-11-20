Feature: An email Delivery holds counts that match Caducus's records
  Caducus keeps the record of each reader. The email Delivery holds counts only: how many readers are queued, sent, failed, suppressed, skipped, delivered,
  bounced and complained, recomputed from Caducus's delivery log every time the worker touches the Delivery, so they always match what Caducus recorded. A reader
  who is suppressed when their turn comes is counted as suppressed and is never mailed. A reader who is on two of the lists a Delivery names gets one message.
  A complaint suppresses the reader for every later send. The Delivery never holds a reader, an address or the words of a message, and nothing here sends a real
  email: Caducus runs in memory with its mailer replaced by a recorder.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And a site "alpha" with the lists "stories" (every story) and "security" (the security section)
    And the Story "slow-water" is at version 3

  Scenario: The counts match the records Caducus kept, and follow what the provider reports later
    Given "reader1@example.test" confirmed "stories"
    And "reader2@example.test" confirmed "stories"
    And "reader3@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text                | lists   |
      | email   | alpha-send | none     | Slow water rises    | stories |
    When the worker sends the email Delivery of "story-published:slow-water" and Caducus works through its queue
    Then the Delivery of "story-published:slow-water" counts "3 sent"
    And Caducus's log for the Delivery of "story-published:slow-water" holds 3 readers: "sent 3"
    And the Delivery of "story-published:slow-water" is "sent"
    When the provider reports a delivery of message 1
    And the provider reports a delivery of message 2
    And the provider reports a permanent bounce of message 3
    And the worker refreshes the counts of the email Delivery of "story-published:slow-water"
    Then the Delivery of "story-published:slow-water" counts "3 sent, 2 delivered, 1 bounced"
    And Caducus's log for the Delivery of "story-published:slow-water" holds 3 readers: "bounced 1, delivered 2"
    And the Delivery of "story-published:slow-water" is "sent"
    And the Delivery's row holds no address and no words of the message

  Scenario: Refreshing again with nothing new changes nothing
    Given "reader1@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists   |
      | email   | alpha-send | none     | Slow water rises | stories |
    When the worker sends the email Delivery of "story-published:slow-water" and Caducus works through its queue
    And the worker refreshes the counts of the email Delivery of "story-published:slow-water"
    And the worker refreshes the counts of the email Delivery of "story-published:slow-water"
    Then the Delivery of "story-published:slow-water" counts "1 sent"
    And the Delivery of "story-published:slow-water" was written for its counts once

  Scenario: A suppressed address is counted as suppressed and is not mailed
    Given "reader1@example.test" confirmed "stories"
    And "reader2@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists   |
      | email   | alpha-send | none     | Slow water rises | stories |
    When the worker sends the email Delivery of "story-published:slow-water"
    And Caducus fans the event out to its readers but mails none yet
    And a complaint from an earlier message about "reader1@example.test" is recorded
    And Caducus mails what it queued
    And the worker settles the email Delivery of "story-published:slow-water"
    Then the Delivery of "story-published:slow-water" counts "1 sent, 1 suppressed"
    And "reader1@example.test" has been mailed 0 messages in all
    And "reader2@example.test" has been mailed 1 message in all
    And the Delivery of "story-published:slow-water" is "sent"

  Scenario: A reader who is on two of the lists gets one message
    Given "both@example.test" confirmed "stories" and "security"
    And "only@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists             |
      | email   | alpha-send | none     | Slow water rises | stories, security |
    When the worker sends the email Delivery of "story-published:slow-water" and Caducus works through its queue
    Then "both@example.test" has been mailed 1 message in all
    And "only@example.test" has been mailed 1 message in all
    And the Delivery of "story-published:slow-water" counts "2 sent"

  Scenario: A complaint suppresses the reader for later sends
    Given "reader1@example.test" confirmed "stories"
    And "reader2@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists   |
      | email   | alpha-send | none     | Slow water rises | stories |
    When the worker sends the email Delivery of "story-published:slow-water" and Caducus works through its queue
    And the provider reports a complaint about message 1
    And the worker refreshes the counts of the email Delivery of "story-published:slow-water"
    Then the Delivery of "story-published:slow-water" counts "2 sent, 1 complained"
    And "reader1@example.test" is suppressed because of a complaint
    Given the Story "fast-river" is at version 1
    And the decision "story-published:fast-river" of kind "story_published" is made for the Story "fast-river" with these Deliveries
      | channel | account    | approval | text           | lists   |
      | email   | alpha-send | none     | Fast river runs | stories |
    When the worker sends the email Delivery of "story-published:fast-river" and Caducus works through its queue
    Then the Delivery of "story-published:fast-river" counts "1 sent"
    And "reader1@example.test" has been mailed 1 message in all
    And "reader2@example.test" has been mailed 2 messages in all

  Scenario: Today shows each send with its counts
    Given "reader1@example.test" confirmed "stories"
    And "reader2@example.test" confirmed "stories"
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account    | approval | text             | lists   |
      | email   | alpha-send | none     | Slow water rises | stories |
    And the Announcement of "story-published:slow-water" is released
    When the worker sends the email Delivery of "story-published:slow-water" and Caducus works through its queue
    And the provider reports a delivery of message 1
    And the worker refreshes the counts of the email Delivery of "story-published:slow-water"
    And Today is read for Tuesday 17 November 2026 in UTC
    Then Today lists 1 email send
    And the send is for the lists "stories" with 1 item and the counts "2 sent, 1 delivered"
    And the send says "✓ Sent" and "no cost recorded"
    And Today prints the line "✓ Sent · stories · 1 item · 2 sent, 1 delivered · no cost recorded"
    And Today made only index reads of the announcement records

  Scenario: A day with no sends lists none
    When Today is read for Tuesday 17 November 2026 in UTC
    Then Today lists 0 email sends

  Scenario: Only an email Delivery has counts
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    When the counts of the Delivery "x" "handle-1" are refreshed
    Then the call is refused saying "only an email Delivery has counts"
