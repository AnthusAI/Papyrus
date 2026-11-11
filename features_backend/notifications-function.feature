Feature: The site's notifications function mails the site's own people
  Caducus runs inside each site's own stack. A published story is turned into one Caducus event whose id comes from the
  story's lineage, so announcing it again changes nothing. Mail goes to the people named in the site's own AWS
  configuration, carries the site's own theme, and records every decision in the site's own delivery log. Nothing is
  shared between sites.

  Background:
    Given a site "alpha" with the notifications plugin and one operator

  Scenario: A published story is mailed once in the site's theme
    When the story "Rates held steady" is published in the "news" section
    And the email queue is played through the sender
    Then 1 email is sent to the operator
    And the email subject is "Rates held steady"
    And the email links to "https://alpha.example.test/news/rates-held-steady.html"
    And the email uses the site's accent colour
    And the email says why the operator received it

  Scenario: Announcing the same story again sends nothing more
    Given the story "Rates held steady" is published in the "news" section
    When the same story announcement arrives again
    And the email queue is played through the sender
    Then 1 email is sent to the operator

  Scenario: A story the list's rule does not match sends nothing
    Given the site's list only covers the "security" section
    When the story "Rates held steady" is published in the "news" section
    Then no email is queued
    And the function answers "ignored"

  Scenario: Sites do not share data
    Given a second site "beta" with the notifications plugin and one operator
    When the story "Rates held steady" is published in the "news" section of "alpha"
    Then the delivery log of "alpha" has 1 delivery
    And the delivery log of "beta" is empty

  Scenario: An unpublished item is ignored
    When an announcement arrives for a story that is no longer published
    Then no email is queued
    And the function answers "ignored"

  Scenario: A malformed announcement is refused without touching the log
    When an announcement arrives with an event id that is not a story event id
    Then the function answers "ignored"
    And the delivery log of "alpha" is empty

  Scenario Outline: Public subscription is not available until Caducus supports public audiences
    When a reader's "<action>" request reaches the function
    Then the function answers with status 503 and the word "unavailable"
    And nothing is stored for any reader

    Examples:
      | action             |
      | subscribe          |
      | confirm            |
      | confirm_page_state |
      | preferences_state  |
      | update_preferences |
      | unsubscribe        |
