Feature: Readers subscribe on the site and manage their notifications, through Caducus
  A site's readers subscribe to its lists by email on the site's own pages. The site's notifications function answers
  every reader action from Caducus's public audience in the site's own table: double opt-in with a confirmation in the
  site's design, consent evidence that matches the form, preferences and one-click unsubscribe by signed links,
  suppression after bounces and complaints, and erasure. Links go to the site's pages, never carry an address, and the
  one machine address in a message is the RFC 8058 one-click endpoint. Nothing here reaches SES, DNS or AWS.

  Background:
    Given a site "alpha" with the lists "stories" (every story) and "security" (the security section)

  Scenario: Subscribing mails one confirmation in the site's design
    When "reader@example.test" subscribes to "stories" on the site
    Then the function answers 202 "check_email"
    And one confirmation in the site's design is mailed to "reader@example.test"
    And its button goes to the site's confirm page with a token and no address

  Scenario: The confirm page is under the site's base path
    Given the site lives under the base path "posts"
    When "reader@example.test" subscribes to "stories" on the site
    Then the confirmation's button goes to "https://alpha.example.test/posts/notifications/confirm/"

  Scenario: A signup that does not carry the form's consent wording is refused
    When "reader@example.test" subscribes to "stories" with the wording "Something else."
    Then the function answers 400 "invalid_consent"
    And nothing is mailed to "reader@example.test"

  Scenario: Nothing reaches a reader until they confirm
    Given "reader@example.test" subscribed to "stories" and did not confirm
    When the story "Rates held steady" is published in the "news" section and sent
    Then no story reaches "reader@example.test"

  Scenario: A confirmed reader gets the stories of the lists they chose
    Given "all@example.test" confirmed "stories"
    And "sec@example.test" confirmed "security"
    When the story "A breach" is published in the "security" section and sent
    Then the story reaches "all@example.test" and "sec@example.test" once each
    When the story "Rates held steady" is published in the "news" section and sent
    Then the story reaches only "all@example.test"

  Scenario: Every story message can be left in one click and managed from its footer
    Given "reader@example.test" confirmed "stories"
    When the story "Rates held steady" is published in the "news" section and sent
    Then the message carries List-Unsubscribe to the site's one-click endpoint and List-Unsubscribe-Post
    And its footer links to the site's preferences and unsubscribe pages
    And its footer shows the site's postal address

  Scenario: One-click unsubscribe stops the next story
    Given "reader@example.test" confirmed "stories"
    And the story "Rates held steady" was published and sent
    When the mail provider posts the one-click unsubscribe from that message
    And the story "Another story" is published in the "news" section and sent
    Then no story reaches "reader@example.test" after the unsubscribe

  Scenario: Turning one list off on the preferences page
    Given "reader@example.test" confirmed "stories" and "security"
    When the reader turns "stories" off on the preferences page
    And the story "A breach" is published in the "security" section and sent
    Then the story reaches only "reader@example.test"
    When the story "Rates held steady" is published in the "news" section and sent
    Then no story reaches "reader@example.test" after the change

  Scenario: A permanent bounce suppresses the reader, and their own opt-in lifts it
    Given "reader@example.test" confirmed "stories"
    And the story "Rates held steady" was published and sent
    When SES reports a permanent bounce for that message
    Then "reader@example.test" is suppressed
    When the reader turns "stories" on again on the preferences page
    Then "reader@example.test" is no longer suppressed
    And the site asked SES to clear "reader@example.test" from the account suppression list

  Scenario: A reader deletes their data
    Given "reader@example.test" confirmed "stories"
    When the reader deletes their data on the preferences page
    Then the function answers 200 "deleted"
    And no row of the site's table holds "reader@example.test"

  Scenario: One network far above what readers do is told to slow down
    When one network submits 30 signups for different addresses
    Then the later ones are answered 429 "slow_down" and mailed nothing
