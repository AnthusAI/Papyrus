Feature: The sender of an email gets one receipt that says what happened to it
  Someone who mails a link to the newsroom cannot see the newsroom, so Papyrus answers by email: what it
  filed, or why it filed nothing. The receipt is sent once, only when there is something true to report,
  and an answer to it comes back to the newsroom's address as a continuation of the same submission.
  A stranger is told plainly that only registered people can submit, and how to sign in.

  Scenario: A processed submission is answered once, and an answer to the receipt returns to the newsroom
    Given an accepted email submission "Paper on reader trust" from "editor@mail.example" that was processed
    When Papyrus reports back to the sender
    Then one receipt is mailed to "editor@mail.example" with a subject ending "processed"
    And an answer to the receipt goes to "submissions@newsroom.example.org"
    And the receipt carries the submission's own id, so an answer continues that submission
    When Papyrus reports back to the sender again
    Then no second receipt is mailed

  Scenario: A submission that failed is answered with the reason
    Given an accepted email submission "Broken link" from "editor@mail.example" that failed with "The page could not be fetched."
    When Papyrus reports back to the sender
    Then one receipt is mailed to "editor@mail.example" with a subject ending "processing failed"
    And the receipt says "The page could not be fetched."

  Scenario: A stranger is told that only registered people can submit, and where to sign in
    Given an email submission "Look at this" from "stranger@mail.example", who is not registered
    When Papyrus reports back to the sender
    Then one receipt is mailed to "stranger@mail.example" with a subject ending "submission not accepted"
    And the receipt says "only registered Papyrus users"
    And the receipt says "Sign in: https://newsroom.example.org"
    And the receipt reports no References

  Scenario: A submission the email agent is still reading gets no receipt yet
    Given an accepted email submission "Five links and a question" from "editor@mail.example" that the email agent has not filed anything from
    When Papyrus reports back to the sender
    Then no receipt is mailed
    And the submission records that its receipt is waiting for the agent to file References

  Scenario: An operator can turn receipts off
    Given an accepted email submission "Paper on reader trust" from "editor@mail.example" that was processed
    And the operator has turned receipts off
    When Papyrus reports back to the sender
    Then no receipt is mailed
