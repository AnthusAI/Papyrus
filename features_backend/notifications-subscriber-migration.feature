Feature: Subscribers and consent live in notifications
  A site that sends through the newsletter plugin moves its readers into the notifications table, which Caducus owns: the
  newsletter's subscribers become subscriptions to the site's lists, the consent evidence each reader gave is copied and
  marked as migrated, a suppressed address stays suppressed, and mail already sent keeps working for a dated period. Nobody is
  asked to confirm again and nobody is mailed by the move. The move is a command an operator runs once per site, with a dry run
  first and a verification after; it is idempotent. Everything here runs on a newsletter table in a local DynamoDB fake and
  Caducus's in-memory stores. Nothing reaches a real table, SES or AWS.

  Background:
    Given a site whose newsletter has the lists "weekly" (the roundup), "alerts-a" and "alerts-b", moving to notifications with the same lists

  Scenario: Moved without re-confirming
    Given "reader@example.com" confirmed "weekly" on the newsletter
    When the migration runs
    Then "reader@example.com" is subscribed to "weekly" in notifications
    And their consent evidence is the original, marked migrated
    And no mail of any kind was sent

  Scenario: Counts match
    Given three readers confirmed "weekly" and "alerts-a" on the newsletter
    And "solo@example.com" confirmed "alerts-a" on the newsletter
    And "bounced@example.com" confirmed "weekly" and then bounced
    When the dry run prints
    Then it counts 3 confirmed on "weekly" and 4 confirmed on "alerts-a"
    And it counts 1 bounce suppression and 5 consent records with evidence
    And it shows the suppressed address masked, never in full
    When the migration runs
    And the migration is verified
    Then every count per list, suppressed address, consent record and old link matches the source

  Scenario: Idempotent
    Given "reader@example.com" confirmed "weekly" and "alerts-a" on the newsletter
    And "bounced@example.com" confirmed "alerts-a" and then bounced
    When the migration runs
    And the migration runs again
    Then the second run imported nobody and found both unchanged
    And the notifications table is exactly what it was after the first run

  Scenario: Old links
    Given "reader@example.com" confirmed "weekly" and "alerts-a" on the newsletter
    And the migration ran
    When "reader@example.com" opens the manage link from an old email
    Then the preferences show "weekly" and "alerts-a" on
    When they use the unsubscribe link for "alerts-a" from an old email
    Then "reader@example.com" is subscribed only to "weekly" in notifications

  Scenario: Old links end on the date the owner chose
    Given "reader@example.com" confirmed "weekly" on the newsletter
    And the migration ran
    When the day after the old-link date has passed
    Then the manage link from an old email is invalid

  Scenario: An old confirmation link is never honoured
    Given "reader@example.com" confirmed "weekly" on the newsletter
    And the migration ran
    Then the confirm link from an old email is invalid

  Scenario: Suppressed stays suppressed
    Given "bounced@example.com" confirmed "alerts-a" and then bounced
    And "held@example.com" confirmed "alerts-a" and was suppressed by hand
    And "fine@example.com" confirmed "alerts-a" on the newsletter
    And the migration ran
    When the story "Rates held steady" is published in the "news" section and mailed
    Then the mail goes only to "fine@example.com"

  Scenario: Roundup readers are not mailed every story
    Given "weekly@example.com" confirmed "weekly" on the newsletter
    And "alerts@example.com" confirmed "alerts-a" on the newsletter
    And the migration ran
    When the story "Rates held steady" is published in the "news" section and mailed
    Then the mail goes only to "alerts@example.com"

  Scenario: Someone who stopped on the newsletter after the first run is stopped in notifications too
    Given "reader@example.com" confirmed "weekly" and "alerts-a" on the newsletter
    And "leaver@example.com" confirmed "alerts-a" on the newsletter
    And the migration ran
    And "reader@example.com" turned "alerts-a" off on the newsletter
    And "leaver@example.com" unsubscribed from everything on the newsletter
    When the migration runs again
    Then "reader@example.com" is subscribed only to "weekly" in notifications
    And "leaver@example.com" is subscribed to nothing in notifications

  Scenario: A signup that never confirmed, and an address that unsubscribed, are not carried
    Given "reader@example.com" confirmed "weekly" on the newsletter
    And "pending@example.com" asked for "weekly" and never confirmed
    And "gone@example.com" confirmed "weekly" and then unsubscribed from everything
    When the dry run prints
    Then it carries 1 subscriber and does not carry 1 pending and 1 unsubscribed
    When the migration runs
    Then "pending@example.com" is subscribed to nothing in notifications
    And "gone@example.com" is subscribed to nothing in notifications

  Scenario: A list the notifications settings do not declare stops the run
    Given "reader@example.com" confirmed "alerts-a" on the newsletter
    And the notifications settings declare only "weekly"
    When the dry run prints
    Then it reports the problem "list_not_declared:alerts-a"
    When the migration is asked to run
    Then it is refused and the notifications table is unchanged

  Scenario: An address that erased itself is never brought back
    Given "reader@example.com" confirmed "weekly" on the newsletter
    And the migration ran
    And "reader@example.com" deleted their data with the old manage link
    When the migration runs again
    Then Caducus refused "r***@example.com" and "reader@example.com" is subscribed to nothing in notifications

  Scenario: The command refuses to write without the freeze and a date
    Given "reader@example.com" confirmed "weekly" on the newsletter
    When the command is run without the freeze statement
    Then it stops and nothing was written

  Scenario: The command verifies a finished move
    Given "reader@example.com" confirmed "weekly" and "alerts-a" on the newsletter
    When the command runs with the freeze statement and the date "2027-06-30"
    And the command verifies
    Then it reports that every count matches

  # The newsletter plugin's subscriber, consent and suppression code is deleted in the change that follows the verified move of
  # both Shipped and Distinctive; until then this cannot be true, so the scenario waits.
  @wip
  Scenario: One owner
    Given the migration is verified on every site
    Then no code in the newsletter plugin reads or writes a subscriber, consent or suppression row
