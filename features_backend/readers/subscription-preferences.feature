Feature: A reader chooses a cadence on the preferences page, and consent is never assumed
  The reader's preferences page shows each family of lists as one choice (every new item, the daily summary, or off) and each newsletter as a tick. Consent belongs to a
  family. A reader consented to a family when they confirmed a list of it, and they hold that consent for as long as they hold a list of the family. So choosing another
  cadence inside a family the reader already holds needs no new confirmation, and what they agreed to, the wording, the time and the form, stays on record. Joining a family
  the reader does not hold, a newsletter they never chose or a family they have left, is not a preference: it needs the same double opt-in the signup form has. The page asks
  Caducus to mail a confirmation to the reader's own address with the site's consent wording it showed, and the list begins only when the reader presses the link. Whatever else
  the same save changed is kept.

  Nobody is enrolled by anything but their own choice. A list added to the site's settings has no members until readers choose it, so adding the daily list does not move the
  weekly newsletter's readers or the every-item readers onto it. A reader who leaves one list by the one-click link of a message leaves that list only, from the next send. A
  reader who unsubscribes from everything leaves every list and is not mailed again. Nothing here is sent anywhere: the mailer is a recorder and every address is a placeholder.

  Background:
    Given a site with the lists "every-item" and "daily" in the family "new-stories" and the list "weekly" in its own family
    And the daily list is sent at "06:00" in "America/New_York"

  Scenario: A new daily list starts empty and nobody is added to it
    Given a site with the lists "every-item" and "weekly" and no daily list yet
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the site adds the daily list to the family "new-stories"
    Then the list "daily" has no members
    And the preferences page shows "weekly" and "every-item" on and "daily" off
    And the family "new-stories" has 1 confirmation records

  Scenario: A new daily list sends a summary to nobody until readers choose it
    Given a site with the lists "every-item" and "weekly" and no daily list yet
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the site adds the daily list to the family "new-stories"
    And the daily summary scheduled for "2026-11-05T06:00" local time is sent
    Then the reader has no daily summary
    And the list "daily" has no members

  Scenario: Switching every new item to the daily summary needs no new opt-in and keeps what the reader agreed to
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    Then the page answers "saved"
    And the preferences page shows "daily" on and "every-item" off
    And no confirmation is mailed to the reader
    And the family "new-stories" holds the confirmation of "2026-11-03T15:00:00Z" with the site's consent wording and the form "notifications"

  Scenario: Switching back to every new item is the same: no new opt-in
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    When the reader chooses "every-item" on the preferences page on "2026-11-04T17:00:00Z"
    Then the page answers "saved"
    And no confirmation is mailed to the reader
    And the family "new-stories" holds the confirmation of "2026-11-03T15:00:00Z" with the site's consent wording and the form "notifications"

  Scenario: Joining a new family sends a confirmation and the list begins only when the reader presses it
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page and agrees to the consent wording on "2026-11-04T17:00:00Z"
    Then the page says a confirmation is on its way for "daily"
    And the preferences page shows "weekly" on and "daily" off
    And one confirmation is mailed to the reader naming "Daily summary"
    And the family "new-stories" holds no confirmation
    When the reader presses the confirmation link on "2026-11-04T17:30:00Z"
    Then the reader is on "daily" and "weekly" and nothing else
    And the reader's membership of "daily" begins at "2026-11-04T17:30:00Z"
    And the family "new-stories" holds the confirmation of "2026-11-04T17:30:00Z" with the site's consent wording and the form "notifications-preferences"

  Scenario: A newsletter the reader never chose needs a confirmation too
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader chooses "weekly" on the preferences page and agrees to the consent wording on "2026-11-04T17:00:00Z"
    Then the page says a confirmation is on its way for "weekly"
    And the preferences page shows "every-item" on and "weekly" off
    And one confirmation is mailed to the reader naming "Weekly newsletter"

  Scenario: Joining a new family without the consent wording is refused and nothing changes
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page without the consent wording on "2026-11-04T17:00:00Z"
    Then the function answers 400 "invalid_consent" to the choice
    And the reader is on "weekly" and nothing else
    And no confirmation is mailed to the reader

  Scenario: Words other than the site's consent wording are not consent
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page with other words than the consent wording on "2026-11-04T17:00:00Z"
    Then the function answers 400 "invalid_consent" to the choice
    And the reader is on "weekly" and nothing else
    And no confirmation is mailed to the reader

  Scenario: The other choices of the same save are kept while a new family waits for its confirmation
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader agrees to the consent wording and saves the preferences "daily" and "weekly" on "2026-11-04T17:00:00Z"
    Then the page says a confirmation is on its way for "weekly"
    And the preferences page shows "daily" on and "every-item" and "weekly" off
    And one confirmation is mailed to the reader naming "Weekly newsletter"

  Scenario: Two new lists of one family cannot be joined together
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader agrees to the consent wording and saves the preferences "weekly", "every-item" and "daily" on "2026-11-04T17:00:00Z"
    Then the function answers 400 "one_cadence_per_family" to the choice
    And no confirmation is mailed to the reader

  Scenario: A reader who left everything is asked again before any list begins
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader unsubscribes from everything on the preferences page on "2026-11-04T10:00:00Z"
    When the reader chooses "every-item" on the preferences page and agrees to the consent wording on "2026-11-04T17:00:00Z"
    Then the page says a confirmation is on its way for "every-item"
    And the reader is on nothing
    And one confirmation is mailed to the reader naming "Every new story"

  Scenario: Consent evidence is stored for each family
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "every-item" on "2026-11-04T09:00:00Z"
    Then the family "weekly" holds the confirmation of "2026-11-03T15:00:00Z" with the site's consent wording and the form "notifications"
    And the family "new-stories" holds the confirmation of "2026-11-04T09:00:00Z" with the site's consent wording and the form "notifications"
    And the family "weekly" has 1 confirmation records

  Scenario: The one-click unsubscribe from one message removes that list only, before the next send
    Given the reader has confirmed "weekly" on "2026-11-01T15:00:00Z"
    And the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the mail provider posts the one-click unsubscribe from the message for "Morning story"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    And the weekly issue scheduled for "2026-11-09T04:00" local time is sent
    Then the reader is still on "weekly" and nothing else
    And the reader has no message for "Afternoon story"
    And the reader has the weekly issue scheduled for "2026-11-09T04:00" local time
    And the reader is not suppressed

  Scenario: Unsubscribe from everything removes every list and nothing more is mailed
    Given the reader has confirmed "weekly" on "2026-11-01T15:00:00Z"
    And the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader unsubscribes from everything on the preferences page on "2026-11-04T10:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    And the weekly issue scheduled for "2026-11-09T04:00" local time is sent
    Then the reader is on nothing
    And the reader is suppressed as "unsubscribed"
    And the reader has no message for "Afternoon story"
    And the reader has no message for "Weekly issue"
