@backend @suggest-once
Feature: A Reference gets one related-items check, when it becomes possible, and the check is never repeated on a schedule
  The Related section of a Reference offers other References and concepts found by comparing its summary vector with the others. That comparison used to be redone
  by an hourly task that planned its work by reading every Reference of the site, and on one site it read the whole corpus every hour to write nothing. The owner's
  rule is one check for related items when a Reference is created, and possibly when it is updated, and never the same check over and over. A check needs the
  Reference's own summary vector, so it starts at the moment that vector is stored: new, or stored again because the text it was made from changed (the vector's
  own content hash). Creating the Reference does not start it, because there is nothing to compare yet; a vote, a star, a retitle, an accept and a reject do not
  start it either, because none of them stores a summary vector. The vector pass puts one message on a queue for the Reference, and a function of its own takes it
  off and makes the check. The record that the Reference was checked, with the hash of the text checked, is one row in the router's table; a message whose hash is
  already recorded is dropped, so a repeated message or a repeated run checks nothing twice. A check that fails is delivered again by the queue, three times in all,
  and then waits in a dead-letter queue that an alarm watches; every outcome is a log line. Nothing walks the corpus to find References that need a check. The
  only way to find References that never got one (for example those whose vectors were stored before this rule) is a command a person runs by hand: it reads the
  site's accepted and pending References once, which is a scan and says so, lists those with no record, and queues them only when asked to write. The queue, the
  records and the backends are fakes in these scenarios.

  Scenario: A Reference is checked once and the record says where
    Given a Reference whose summary vector was just stored with the text hash "h1"
    When its check runs
    Then suggestions are made for it and a record is stored under the router's table for that Reference with the hash "h1"

  Scenario: A repeated message or a repeated run does not check the Reference again
    Given a Reference whose summary vector was just stored with the text hash "h1"
    When its check runs
    And the same message is delivered again
    Then the vector search ran once

  Scenario: Changed text is checked again and replaces the record
    Given a Reference whose summary vector was just stored with the text hash "h1"
    When its check runs
    And a message arrives for the same Reference with the hash "h2"
    Then the vector search ran twice and the record holds the hash "h2"

  Scenario: A check that fails is delivered again and records nothing
    Given a Reference whose summary vector was just stored with the text hash "h1"
    And the vector search fails
    When its check runs
    Then the batch reports the message as failed
    And no record is stored

  Scenario: A vote, a star, an accept and a reject start no check
    Given a site whose References are all indexed and checked
    When editors vote on, star, accept and reject some of them and the vector pass runs
    Then no message was put on the suggestion queue

  Scenario: The queue gives a failing check three tries, then a dead-letter queue with an alarm
    Given the monitoring template and its suggestion queue
    Then the suggestion queue redrives to its dead-letter queue after 3 receives
    And an alarm watches the dead-letter queue
    And no schedule starts a suggestion task

  Scenario: The by-hand command lists the References with no record and queues nothing unless asked to write
    Given a site with 3 accepted or pending References of which one has a record
    When the command runs without write
    Then it reports 2 unchecked References, says it scanned all of them, and queues nothing
    When the command runs with write
    Then 2 messages are queued, one for each unchecked Reference

  Scenario: The calibration is read only when a check is about to run
    Given a Reference whose summary vector was just stored with the text hash "h1"
    When its check runs
    And the same message is delivered again
    Then the calibration was read once
