Feature: A record that is due and untouched is shown as Overdue and flagged once
  Every record that waits keeps a named due time in a sparse due index, and a timer puts one wake on the site's queue at that time. A lost timer or a dead wake must
  never be silent. A record still in its due index after the queue's own limits are used up (the runner's whole possible length, twice, as the queue delivers a wake
  at most twice) has no wake in flight and was not run: it is Overdue. Today lists it in words with a mark, first, before what ran. The operations hygiene agent's
  daily wake sends the record's wake again with the key its timer would have used, so a repeat inside the queue's window is dropped and a repeat after it is answered
  as a duplicate and runs nothing twice. It raises one flag for each overdue record and the time it missed, however many times it checks. A record that ran late has a
  new due time or none, so it is no longer in the index and no longer Overdue. Nothing here does the record's work: recovery goes through the same path as the timer.

  Background:
    Given a site whose clock reads "2026-11-19T12:00:00Z"
    And the site's follow-up timers for its Deliveries

  Scenario: A Delivery whose timer was lost shows as Overdue on Today
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When an editor opens Today
    Then Today lists the Delivery "weekly" as Overdue, in words with a mark
    And the Overdue lines come before what ran

  Scenario: A Delivery that is only just due is not Overdue, because its wake is still in flight
    Given the Delivery "daily" waits for its release at "2026-11-19T11:45:00Z" and its timer has fired
    When an editor opens Today
    Then nothing is Overdue

  Scenario: A Delivery with nothing pending is never Overdue
    Given the Delivery "sent" waits for nothing
    When an editor opens Today
    Then nothing is Overdue

  Scenario: The wake is sent again with the key its timer would have used
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When the hygiene agent's daily wake checks what is overdue
    Then one wake was sent again for the Delivery "weekly"
    And its message is the message the Delivery's own timer sends, with the same wake key

  Scenario: The re-sent wake does the work once
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When the hygiene agent's daily wake checks what is overdue
    And the runner takes the re-sent wake
    And the hygiene agent's daily wake checks what is overdue again after the queue forgot the first message
    And the runner takes the re-sent wake
    Then the site has exactly one run record for the Delivery "weekly"
    And the second answer says duplicate

  Scenario: One flag for each overdue record, not one for each check
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When the hygiene agent's daily wake checks what is overdue
    And the hygiene agent's daily wake checks what is overdue again after the queue forgot the first message
    Then the site has exactly one flag about the Delivery "weekly"
    And the first check raised the flag and the second found it already raised

  Scenario: Two overdue records are two wakes and two flags
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    And the Delivery "monthly" waits for its release at "2026-11-19T08:00:00Z" and its timer fired into a queue that lost it
    When the hygiene agent's daily wake checks what is overdue
    Then the site has exactly one flag about the Delivery "weekly"
    And the site has exactly one flag about the Delivery "monthly"
    And Today lists "monthly" before "weekly", the oldest due time first

  Scenario: A record that ran late is no longer Overdue
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When the Delivery "weekly" runs late and waits for nothing
    And an editor opens Today
    Then nothing is Overdue
    And the hygiene agent's daily wake finds nothing to send

  Scenario: A record that misses a later due time is a new flag
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    And the hygiene agent's daily wake checks what is overdue
    When the Delivery "weekly" waits for its release at "2026-11-19T10:00:00Z" and its timer fired into a queue that lost it
    And the hygiene agent's daily wake checks what is overdue
    Then the site has exactly two flags about the Delivery "weekly"

  Scenario: What counts as long enough is the queue's own limits
    Then a record is overdue only after the runner's whole possible length, twice, has passed
    And the limits are the ones the wake queue template sets

  Scenario: Today never lists the whole Delivery table to find what is overdue
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When an editor opens Today
    Then every Delivery read was a query on the due index
