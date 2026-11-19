Feature: An agent's definition says what runs one at a time, and the queue enforces it
  A wake's message group is the agent plus its serial scope, and the scope comes from the agent definition's serialBy. With serialBy subject,
  wakes about one Story run one after the other and wakes about different Stories run together. With serialBy agent, every wake of the agent
  passes through one group, so the agent runs one at a time whatever its wakes are about; this is for anything that spends from one budget or
  posts to one account. With serialBy key:<name>, the scope is the value the wake names, such as a channel account, so each account has its own
  lane. A group never runs two wakes at once, and a slow run delays only its own group. A wake with no serialBy is a subject wake. A key
  scope with no value, or a serialBy that is none of the three, is not a wake, and nothing is put on the queue.

  The queue's own ordering is the behaviour of Amazon SQS; these scenarios use a model of the queue that follows its rules and check which
  group Papyrus puts each wake in.

  Background:
    Given the site "distinctive" with a model of its wake queue

  Scenario: Two changes to one Story run in order
    Given the agent "announce" runs one at a time by subject
    When two wakes about the Story "story-1" arrive
    Then the two messages are in the same group
    When the runner receives the first message and is still running it
    Then the queue gives the runner no other message while it holds the first

  Scenario: Changes to two Stories run together
    Given the agent "announce" runs one at a time by subject
    When wakes about the Stories "story-1" and "story-2" arrive
    Then the two messages are in different groups
    When the runner receives the first message and is still running it
    Then the queue gives the runner the second message while it holds the first

  Scenario: An agent that runs one at a time as a whole holds every Story in one group
    Given the agent "announce" runs one at a time by agent
    When wakes about the Stories "story-1" and "story-2" arrive
    Then the two messages are in the same group
    When the runner receives the first message and is still running it
    Then the queue gives the runner no other message while it holds the first

  Scenario: A slow run delays only its own group
    Given the agent "announce" runs one at a time by agent
    And the agent "copy-edit" runs one at a time by subject
    When wakes about the Stories "story-1" and "story-2" arrive for "announce"
    And a wake about the Story "story-1" arrives for "copy-edit"
    And the runner receives the first message and is still running it
    Then the queue gives the runner the copy-edit message while it holds the first

  Scenario: Each channel account has its own lane
    Given the agent "announce" runs one at a time by the key "account"
    When wakes arrive for the account "first-account" and the account "second-account"
    Then the two messages are in different groups
    When wakes arrive for the account "first-account" again
    Then that message is in the same group as the first account's first message

  Scenario: A key scope with no value is not a wake
    Given the agent "announce" runs one at a time by the key "account"
    When a wake arrives that names no account
    Then the wake is refused and the queue holds no message

  Scenario: A serial scope that is none of the three is not a wake
    Given the agent "announce" runs one at a time by "everything"
    When a wake about the Story "story-1" arrives
    Then the wake is refused and the queue holds no message

  Scenario: A wake with no serial scope is a subject wake
    When two wakes about different Stories arrive from an automation that has no definition
    Then the two messages are in different groups
