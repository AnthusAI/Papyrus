Feature: The router backs off from the lab instead of asking about every job on every run
  When the lab is struggling it answers 429 or 503. The router then stops calling the lab for the whole monitor
  until the lab's Retry-After has passed (or, with no Retry-After, an exponential wait). A job that is still
  running is not asked about again until its own wait is over, and the collector asks oldest job first and
  stops at the first refusal. These are backoffs, not limits: every job stays recorded and is asked about again
  later, and nothing is ever dropped.

  Background:
    Given a router with three stories whose lab jobs are still running

  Scenario: A 429 with Retry-After pauses every lab call until then
    Given the lab answers 429 and asks the router to wait ninety seconds
    When the collector asks the lab about the jobs
    Then the monitor records that the lab is paused for ninety seconds
    When the collector and the route task run thirty seconds later
    Then both stopped because of the lab backoff and the lab received no call
    When the lab has recovered and the collector asks after the pause
    Then the stories are delivered and the pause is cleared

  Scenario: Without a Retry-After the pause grows with each refused run
    Given the lab answers 503 without a Retry-After
    When the collector is refused three times in a row, each time after the pause
    Then the pauses were sixty, one hundred and twenty and two hundred and forty seconds

  Scenario: A job that is still running waits longer each time it is checked
    When the collector asks and then asks again before the job's wait is over
    Then the lab was asked about each job once and not again inside its wait
    When the collector asks again after the wait
    Then each job's next wait is twice as long

  Scenario: The collector stops at the first 429 and drops no job
    Given the lab answers 429 and asks the router to wait ninety seconds
    When the collector asks the lab about the jobs
    Then the collector asked the lab about only the oldest job
    And all three stories still have their jobs recorded
