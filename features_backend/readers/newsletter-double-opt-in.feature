Feature: Newsletter double opt-in
  A visitor asks for a newsletter by giving an address and choosing lists. The site answers the same way whatever it
  knows about the address, mails a confirmation link, and subscribes the address only when the link is used. The link
  works once, expires, and a page that merely shows it changes nothing.

  Background:
    Given a site whose newsletter plugin offers the lists "weekly", "alerts-a" and "alerts-b"

  Scenario: A new address is pending until it confirms
    When a visitor asks for "weekly" with "reader@example.com"
    Then the answer is "check_email"
    And 1 confirmation email is sent naming "Weekly roundup"
    And "reader@example.com" is "pending" and is not a member of "weekly"
    When the visitor confirms with the emailed link
    Then the answer is "confirmed"
    And "reader@example.com" is "confirmed" and is a member of "weekly"
    And the consent evidence records the wording, the page and both addresses

  Scenario: The confirmation link works once
    Given "reader@example.com" has asked for "weekly"
    When the visitor confirms with the emailed link
    And the visitor confirms with the emailed link
    Then the answer is "expired"

  Scenario: Showing the confirmation page changes nothing
    Given "reader@example.com" has asked for "weekly"
    When the confirmation page is shown for the emailed link
    Then "reader@example.com" is "pending" and is not a member of "weekly"

  Scenario: The link expires after 72 hours
    Given "reader@example.com" has asked for "weekly"
    When 73 hours pass
    And the visitor confirms with the emailed link
    Then the answer is "expired"
    And "reader@example.com" is "pending" and is not a member of "weekly"

  Scenario: Asking again replaces the earlier link
    Given "reader@example.com" has asked for "weekly"
    When 2 hours pass
    And a visitor asks for "weekly" with "reader@example.com"
    Then 2 confirmation emails have been sent
    When the visitor confirms with the first emailed link
    Then the answer is "expired"

  Scenario: A confirmed subscriber who adds a list confirms only the new list
    Given "reader@example.com" has asked for "weekly" and confirmed
    When 2 hours pass
    And a visitor asks for "weekly,alerts-b" with "reader@example.com"
    Then the newest confirmation email names "Alerts B" but not "Weekly roundup"

  Scenario Outline: The answer does not reveal what the site knows about an address
    Given an address in the state "<state>"
    When a visitor asks for "weekly" with that address
    Then the answer is "check_email"

    Examples:
      | state            |
      | new              |
      | pending          |
      | confirmed        |
      | suppressed       |
      | rate limited     |
      | mail unavailable |

  Scenario Outline: A suppressed or rate limited request sends nothing
    Given an address in the state "<state>"
    When a visitor asks for "weekly" with that address
    Then no confirmation email is sent

    Examples:
      | state        |
      | suppressed   |
      | rate limited |

  Scenario Outline: Automated or malformed submissions are refused or ignored
    When a visitor asks for "weekly" with "<email>" <how>
    Then the answer is "<answer>"
    And no confirmation email is sent
    And nothing is stored

    Examples:
      | email              | how                               | answer        |
      | reader@example.com | with the hidden field filled      | check_email   |
      | reader@example.com | one second after rendering        | check_email   |
      | reader@example.com | a day and an hour after rendering | check_email   |
      | not-an-address     | normally                          | invalid_email |

  Scenario Outline: A mail scanner's HEAD request never confirms or unsubscribes
    Given "reader@example.com" has asked for "weekly"
    When a mail scanner sends HEAD to the legacy <route> link
    Then the link answers 302 to the clean "<page>" page with no body
    And "reader@example.com" is "pending" and is not a member of "weekly"

    Examples:
      | route       | page                   |
      | confirm     | /newsletter/confirm/   |
      | preferences | /newsletter/preferences/ |
      | unsubscribe | /newsletter/unsubscribe/ |
