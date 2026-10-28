Feature: Held email submissions are released or discarded by an editor
  Email is untrusted source material. When a message fails sender authentication checks, or was
  refused by the earlier authentication gate, it is held in private quarantine: an inert text
  rendering, the SES verdicts and every extracted link, readable only by editors of the
  destination publication. Nothing is routed while it is held. An editor or admin decides:
  Accept (release) queues it exactly as if it had been accepted, so its links can be added to
  References; Reject (discard) closes it. Each decision is recorded with the person and an
  optional reason. Authentication signals and sender claims never grant a role, never pick a
  destination and never decide anything.

  Scenario: A message that fails authentication is quarantined and nothing is routed
    Given a publication email destination and a newsletter whose SES authentication checks failed
    When the quarantine receiver processes the SES delivery
    Then the message is held in quarantine as data-only
    And its inert text, verdicts and both extracted links are available to the publication's editors
    And no discoveries exist for the router or classifier
    And no editor directory lookup was made

  Scenario: An editor accepts a held message and it is queued as if it had been accepted
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    When an editor accepts the held message because they know the newsletter
    And the receiver applies the recorded decision and finishes the queue
    Then the message is queued with one discovery for each of its links
    And the decision is recorded with the editor, the time, the reason and the verdict snapshot
    And the links can now be added to References

  Scenario: Accepting twice does nothing new
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    And an editor has accepted the held message and the receiver has queued it
    When the editor accepts the same message again
    Then the second request reports the existing decision
    And no further discovery, manifest or receipt change is made

  Scenario: The reason can be added or changed after the decision, until the receiver has applied it
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    When an editor rejects the held message with no reason
    And the editor rejects the same message again and explains why
    Then the recorded reason is the explanation and the decision is unchanged
    And a plain repeat of the decision, with no reason, changes nothing
    When the receiver applies the recorded decision
    And the editor tries to change the reason once more
    Then the receipt keeps the reason it was applied with

  Scenario: An editor rejects a held message and nothing is ever routed
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    When an editor rejects the held message because it is not for this publication
    And the receiver applies the recorded decision
    Then the message is closed as rejected and keeps its private record for the retention period
    And the rejection is recorded with the editor, the time and the reason
    And no discoveries exist for the router or classifier

  Scenario: The first decision stands
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    When an editor rejects the held message because it is not for this publication
    And a second request tries to accept the same message
    Then the second request is refused as already decided
    And the message is never queued

  Scenario: A held message is read-only until it is accepted
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    Then no article link of the held message can be resolved or added to References

  Scenario: A sender who claims to be an editor gains nothing
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the newsletter is sent from an address that belongs to an editor and says it is from the editor
    When the quarantine receiver processes the SES delivery
    Then the message is held in quarantine as data-only
    And no editor directory lookup was made
    And a person without an editor session cannot accept it
    And the held message stays held

  Scenario: An editor of another publication cannot decide
    Given a publication email destination and a newsletter whose SES authentication checks failed
    And the quarantine receiver has processed the SES delivery
    Then an editor of a publication the message is not routed to cannot accept or reject it

  Scenario: Spam and virus failures are never held for release
    Given a publication email destination and a newsletter that failed the SES spam check
    When the quarantine receiver processes the SES delivery
    Then the message is refused and no text or links are stored
    And an editor cannot accept it

  Scenario: The two messages refused by the earlier authentication gate can be held and accepted
    Given two receipts refused by the earlier authentication gate whose private mail is still stored
    When the operator quarantines the refused receipts
    Then both receipts are held in quarantine with their original fields preserved
    And their verdicts show as unavailable because none were recorded
    And repeating the operator step changes nothing
    When an editor accepts each held message and the receiver finishes the queue
    Then both messages are queued with discoveries for their links
