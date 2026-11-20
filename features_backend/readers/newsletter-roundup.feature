Feature: Newsletter roundup issues
  The weekly roundup is drafted from the week's published items, written up in the newsroom editor, approved by an admin
  for a time, and only then mailed, once to each subscriber. An approval is an approval of exactly what was read: an edit
  afterwards takes the issue back to draft.

  Background:
    Given a site with a weekly roundup and 3 confirmed subscribers
    And the week's published items have been drafted into an issue

  Scenario: Nothing sends without approval
    When the schedule fires the send for the issue
    Then no email is sent
    And the issue is "draft"

  Scenario: Only an admin approves
    When an editor tries to approve the issue
    Then the answer is refused
    And the issue is "draft"
    When an admin approves the issue for an hour from now
    Then the issue is "scheduled"
    And a one-time schedule is set for the issue

  Scenario: An issue edited after approval is not sent
    Given an admin approves the issue for an hour from now
    When an editor changes the issue body
    And the schedule fires the send for the issue
    Then no email is sent
    And the issue is "draft"
    And the issue note says "edited after approval; approve again"

  Scenario: An approved issue is mailed once to each subscriber
    Given an admin approves the issue for an hour from now
    When the schedule fires the send for the issue
    And the worker handles the queued messages
    Then 3 emails are sent, each to a different subscriber
    And every email carries a one-click unsubscribe header
    And the issue is "sent"
    And the issue is published to the archive

  Scenario: A retried batch never mails anyone twice
    Given an admin approves the issue for an hour from now
    When the schedule fires the send for the issue
    And the worker handles the queued messages
    And the queue delivers the same messages again
    Then 3 emails are sent, each to a different subscriber
    And the issue is "sent"
    And the issue is published to the archive once

  Scenario: A missing postal address blocks the send
    Given an admin approves the issue for an hour from now
    And the postal address is not configured
    When the schedule fires the send for the issue
    Then no email is sent
    And the issue is "blocked"
