Feature: Signup plugin guest submissions
  An anonymous visitor can submit an email address to a signup form through one
  narrow operation. The operation limits what it accepts, ignores bots without
  telling them, stores each address once, and refuses a caller that sends too
  many requests. Nothing a guest sends is ever read back to them.

  Background:
    Given a site whose signup plugin accepts the form "newsletter"

  Scenario: A valid address is stored once however often it is sent
    When a guest submits "reader@example.test" to "newsletter" 3 times
    Then every answer says "accepted"
    And 1 signup entry is stored

  Scenario: A bot that fills the hidden field is told it worked and is not stored
    When a guest submits "bot@example.test" to "newsletter" with the hidden field filled
    Then every answer says "accepted"
    And 0 signup entries are stored

  Scenario: A form submitted instantly is not stored
    When a guest submits "fast@example.test" to "newsletter" half a second after the page rendered
    Then every answer says "accepted"
    And 0 signup entries are stored

  Scenario Outline: Malformed or hostile input is refused and not stored
    When a guest submits "<value>" to "<form>"
    Then every answer says "invalid"
    And 0 signup entries are stored

    Examples:
      | value                        | form       |
      | not-an-address               | newsletter |
      | =HYPERLINK@example.test      | newsletter |
      | reader@example.test          | other      |
      | a@b                          | newsletter |

  Scenario: An oversized value is refused and not stored
    When a guest submits a value of 5000 characters to "newsletter"
    Then every answer says "invalid"
    And 0 signup entries are stored

  Scenario: The twenty-first request in a minute from one address is throttled
    When one address makes 25 submissions of different addresses in one minute
    Then the first 20 answers say "accepted"
    And the last 5 answers say "throttled"
    And 20 signup entries are stored

  Scenario: The limit starts over in the next minute
    Given one address has made 25 submissions in one minute
    When the next minute begins and the same address submits "later@example.test" to "newsletter"
    Then every answer says "accepted"
