Feature: The site's notifications function mails the site's own readers
  Caducus runs inside each site's own stack. A published story is turned into one Caducus event whose id comes from the
  story's lineage, so announcing it again changes nothing. The event names the lists whose rule matches the story, and
  mail goes to the readers who subscribed to those lists and confirmed. It carries the site's own theme, and every
  decision is recorded in the site's own delivery log. Nothing is shared between sites.

  Background:
    Given a site "alpha" with the notifications plugin and one confirmed subscriber

  Scenario: A published story is mailed once in the site's theme
    When the story "Rates held steady" is published in the "news" section
    And the email queue is played through the sender
    Then 1 email is sent to the subscriber
    And the email subject is "Rates held steady"
    And the email links to "https://alpha.example.test/news/rates-held-steady.html"
    And the email uses the site's accent colour
    And the email says why the subscriber received it

  Scenario: Announcing the same story again sends nothing more
    Given the story "Rates held steady" is published in the "news" section
    When the same story announcement arrives again
    And the email queue is played through the sender
    Then 1 email is sent to the subscriber

  Scenario: A story the list's rule does not match sends nothing
    Given the site's list only covers the "security" section
    When the story "Rates held steady" is published in the "news" section
    Then no email is queued
    And the function answers "ignored"

  Scenario: Sites do not share data
    Given a second site "beta" with the notifications plugin and one confirmed subscriber
    When the story "Rates held steady" is published in the "news" section of "alpha"
    And the email queue is played through the sender
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

  Scenario Outline: Every reader action is answered by the site's public audience
    When a reader's "<action>" request reaches the function
    Then the function does not answer 503

    Examples:
      | action             |
      | subscribe          |
      | confirm            |
      | confirm_page_state |
      | preferences_state  |
      | update_preferences |
      | unsubscribe        |
      | delete_subscriber  |
