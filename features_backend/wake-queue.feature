Feature: Every site has one wake queue, and the procedure runner consumes it
  A wake is one message on the site's FIFO queue: the wake key, the agent, the subject and the reason. The message group is the agent plus the
  subject, so wakes about one subject run one after the other and wakes about different subjects run at the same time. The deduplication id is
  the wake key. The procedure runner takes one message at a time and holds it for the whole run. It gives the message back (a return) only
  once the wake's run record exists; if it dies or cannot make the record, the message stays and the queue delivers it again, and after the
  second delivery it moves to the dead-letter queue, which has an alarm. The monitoring router, Run now, the story-stage triggers and
  translate-on-publish put wakes on the queue and start nothing else.

  The queue's own behaviour (first in, first out per group, the five-minute deduplication window, redelivery, the dead-letter move and its
  alarm) is the behaviour of Amazon SQS and is set by the queue's template: the template's properties are checked by
  scripts/test-agents-stack.ts. These scenarios use a model of the queue that follows the same rules, and check what Papyrus does with them.
  The queue's own duplicate drop is shown once on a real site when the queue is enabled there.

  Background:
    Given the site "distinctive" with its wake queue and the runner that consumes it

  Scenario: A wake starts exactly one run
    When a monitor delivers two new decisions and the router puts their wakes on the queue
    Then the queue holds 2 messages, one wake for each decision
    And each message names the agent, the subject and the reason in words
    When the runner takes the message
    Then the site has 1 run record, made from the wake key
    And the procedure ran once
    And the message is deleted

  Scenario: Two wakes for the same group run one after the other
    Given two wakes from one agent about the same story
    Then the two messages are in the same group
    When the runner receives the first message and is still running it
    Then the queue gives the runner no other message while it holds the first
    When the runner finishes that run and the message is deleted
    Then the runner takes the second message
    And the procedure ran twice, one run after the other

  Scenario: Two wakes for different groups run at the same time
    When a monitor delivers two new decisions and the router puts their wakes on the queue
    Then the two messages are in different groups
    When the runner receives the first message and is still running it
    Then the queue gives the runner the second message while it holds the first

  Scenario: A duplicate wake inside the deduplication window is dropped
    When the same wake is put on the queue twice inside the window
    Then the queue holds 1 message
    And both messages carry the same deduplication id, made from the wake key

  Scenario: A duplicate wake after the window runs once
    When the same wake is put on the queue twice, the second after the window
    Then the queue holds 2 messages
    When the runner takes each message in turn
    Then the site has 1 run record, made from the wake key
    And the procedure ran once
    And the second message answered "duplicate" and both messages are deleted

  Scenario: A runner that dies leaves the message on the queue
    Given a wake on the queue
    And the runner dies before it has made the run record
    When the runner takes the message
    Then the message is not deleted
    When the queue delivers the message again and the runner is alive
    Then the site has 1 run record, made from the wake key
    And the message is deleted

  Scenario: A wake the site refuses to start keeps its message
    Given a wake on the queue for a procedure the site does not have
    When the runner takes the message
    Then no run record exists and the message is not deleted
    When the runner takes the message once more
    Then the next delivery moves the message to the dead-letter queue

  Scenario: A message the runner cannot parse reaches the dead-letter queue
    Given a message on the queue that is not a wake
    When the runner takes the message
    Then the runner refuses it and makes no run record
    And the message is not deleted
    When the runner takes the message once more
    Then the next delivery moves the message to the dead-letter queue
    And the dead-letter queue holds 1 message

  Scenario: A wake whose reason does not match its key is not a wake
    Given a message whose wake says another agent than its key does
    When the runner takes the message
    Then the runner refuses it and makes no run record

  Scenario: The dead-letter queue is empty when every wake ran
    When a monitor delivers two new decisions and the router puts their wakes on the queue
    And the runner takes and finishes every message
    Then the queue is empty
    And the dead-letter queue holds 0 messages

  Scenario: Run now goes through the queue
    Given an automation with a router publication for the site
    When an editor runs it now
    Then the queue holds 1 message
    And the message's reason says the editor ran it now
    And no function was invoked directly

  Scenario: A story-stage trigger goes through the queue
    Given a story-stage automation for the site
    When a story enters the stage
    Then the queue holds 1 message
    And no function was invoked directly

  Scenario: A site whose queue does not exist records the start as failed
    Given a site "no-queue-yet" whose wake queue does not exist
    When a monitor delivers two new decisions and the router puts their wakes on the queue
    Then the router counts 2 failed starts
    And nothing started the runner another way

  Scenario: Distinctive Mark's ruling analysis runs through the queue
    When a monitor delivers two new decisions and the router puts their wakes on the queue
    And the runner takes and finishes every message
    Then the ruling analysis ran once for each decision
    When the monitor delivers the same decisions again
    Then the queue holds no new message
