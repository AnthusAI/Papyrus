Feature: A Delivery under soft review posts by itself at its scheduled time
  The owner's goal (Ryan, 2026-11-22): "The announcement is automatically created and scheduled. I might intervene and tweak it before it automatically posts on
  that schedule, or I might not. This needs to be configurable, since many sites will require human approval before posting."

  A Delivery is drafted with an edit window (the editWindows setting): it may go at its release time and locks for the send at its lock time. Its earliest
  pending time has a follow-up timer. When the timer fires, the runner starts the engine's procedure deliver_due with no adopted agent; only the site's pause
  stops it. The run reads the Delivery again, raises the lock when its time has come and sends what is due through the announce agent's own deliver steps, with
  their guards. Under soft review a Delivery nobody acted on is approved by the policy and posts; a person's edit before the lock is what posts; a person's stop
  before the lock means nothing posts. Under hard review the lock time with no approval raises one flag for a person and posts nothing.

  Background:
    Given a site backend with the published procedure "deliver_due"
    And X announcements are On for the account "mom" with a budget of $10.00
    And the site's Deliveries set follow-up timers

  Scenario: A soft Delivery posts at its lock time with nobody acting
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    Then the Delivery's timer is set for "2026-11-22T10:00:00Z"
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run was acted with the reason "sent" and names no responsibility and no rung
    And the Delivery was approved by the policy at "2026-11-22T10:00:00Z" and locked with version 1
    And Caducus was handed the drafted words
    And the Delivery has no timer

  Scenario: A lock before the release locks first and posts at the release
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, locked at "2026-11-22T09:50:00Z" and released at "2026-11-22T10:00:00Z"
    When the time "2026-11-22T09:50:00Z" arrives and each wake reaches the runner
    Then the deliver run was acted with the reason "locked" and names no responsibility and no rung
    And the Delivery's timer is set for "2026-11-22T10:00:00Z"
    And Caducus was handed nothing
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run was acted with the reason "sent" and names no responsibility and no rung
    And Caducus was handed the drafted words

  Scenario: A person's edit before the lock posts the edited words
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the person "ada" saves the words "Edited by a person.\n\nhttps://machines.example/s" over version 1 through the announcements write door at "2026-11-22T09:30:00Z"
    And the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run was acted with the reason "sent" and names no responsibility and no rung
    And the Delivery was approved by the policy at "2026-11-22T10:00:00Z" and locked with version 2
    And Caducus was handed the words "Edited by a person.\n\nhttps://machines.example/s"

  Scenario: A person's stop before the lock posts nothing
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the person "ada" withdraws the Delivery at "2026-11-22T09:30:00Z"
    And the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run says nothing to do with the reason "not_waiting"
    And Caducus was handed nothing
    And the Delivery is "withdrawn"

  Scenario: A person's change to hard review before the lock waits for a person
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the person "ada" changes the Delivery's review to "hard" through the announcements write door at "2026-11-22T09:30:00Z"
    And the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run asked a person with the reason "waiting_for_person"
    And Caducus was handed nothing

  Scenario: A hard Delivery at its lock time with no approval raises one flag and posts nothing
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "hard" review, released and locked at "2026-11-22T10:00:00Z"
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run asked a person with the reason "waiting_for_person"
    And exactly one flag is open for the Delivery
    And Caducus was handed nothing
    And the Delivery is still due at "2026-11-22T10:00:00Z"
    When the hygiene agent sends the Delivery's wake again with its timer's key
    Then exactly one flag is open for the Delivery
    And Caducus was handed nothing

  Scenario: A hard Delivery a person approved before the lock posts at its time
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "hard" review, released and locked at "2026-11-22T10:00:00Z"
    When the person "ada" releases the Delivery through the announcements write door at "2026-11-22T09:30:00Z"
    And the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then the deliver run was acted with the reason "sent" and names no responsibility and no rung
    And Caducus was handed the drafted words

  Scenario: A deliver wake for a moved time does nothing
    Given an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    And its timer fired at "2026-11-22T10:00:00Z" and the wake waits on the queue
    When the Delivery's release moves to "2026-11-22T11:00:00Z" before the wake runs
    And the wake on the queue reaches the runner at "2026-11-22T10:00:00Z"
    Then the deliver run says nothing to do with the reason "not_waiting"
    And Caducus was handed nothing
    And the Delivery's timer is set for "2026-11-22T11:00:00Z"

  Scenario: A paused site sends nothing
    Given an admin paused the site because "Incident"
    And an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    Then no procedure ran
    And the deliver run says nothing to do with the reason "paused"
    And Caducus was handed nothing
    And the Delivery is still due at "2026-11-22T10:00:00Z"

  Scenario: Paused announcements send nothing: Caducus's guard refuses the post
    Given the owner paused announcements
    And an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    And Caducus runs its x queue and the deliver side reads what it recorded
    Then the Delivery is blocked with the reason "paused"
    And nothing was posted to X

  Scenario: The budget guard still holds
    Given $9.90 is already spent on X this cycle
    And an X Delivery drafted at "2026-11-22T09:00:00Z" under "soft" review, released and locked at "2026-11-22T10:00:00Z"
    When the time "2026-11-22T10:00:00Z" arrives and each wake reaches the runner
    And Caducus runs its x queue and the deliver side reads what it recorded
    Then the Delivery is blocked with the reason "budget reached"
    And nothing was posted to X
    And announcements are paused because the budget was reached
