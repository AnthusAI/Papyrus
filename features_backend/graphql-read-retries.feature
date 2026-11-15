Feature: A read that fails for a moment is sent again, with a growing pause, and a write is never sent again by that rule
  A big command such as `papyrus stories localize --all --dry-run` makes thousands of reads, and over that many a reset connection or a data-store timeout
  is certain to happen. A read changes nothing, so the client sends it again after a pause that doubles each time (with jitter, so many workers do not return
  together), up to five attempts, when the failure is the network's or the data store's: a reset connection, a timeout, a throttled or briefly unavailable
  service, or an answer whose only errors are the store's own transient ones (AppSync reports a DynamoDB client timeout inside an otherwise normal answer).
  A request the service refused (validation, credentials, authorization) is not sent again, because the answer cannot change. A write is never sent again
  by this rule, because it may already have run. When the attempts run out, the last failure is raised with its real message; nothing is swallowed.

  Scenario: A reset connection is retried after a pause
    Given a site whose connection resets twice and then answers
    When the client reads a Story
    Then the read returns the Story
    And the client attempted the read 3 times
    And it paused 2 times, the second pause longer than the first

  Scenario: A data-store timeout reported inside the answer is retried
    Given a site whose first answer reports a DynamoDB client timeout and whose second answer is the Story
    When the client reads a Story
    Then the read returns the Story
    And the client attempted the read 2 times

  Scenario: A refused request is not retried
    Given a site that answers a read with a validation error
    When the client reads a Story
    Then the read fails with the validation error
    And the client attempted the read 1 times

  Scenario: A read that never succeeds fails with the real message after five attempts
    Given a site whose connection always resets
    When the client reads a Story
    Then the read fails mentioning "Connection reset by peer"
    And the client attempted the read 5 times

  Scenario: A write is not sent again after a transient answer
    Given a site whose first answer reports a DynamoDB client timeout and whose second answer is the Story
    When the client writes a Story
    Then the write fails mentioning "connection timed out"
    And the client attempted the read 1 times
