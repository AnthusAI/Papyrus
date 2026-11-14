Feature: The router paces its lab calls under the API Gateway limit and retries a bare 429 shortly
  The lab's HTTP API sits behind an API Gateway stage that allows 5 requests a second sustained. That is a real
  constraint, so the router keeps to 4 a second (configurable as cyclotron.maxRequestsPerSecond) across every POST,
  GET and feedback call in an invocation. A 429 with no Retry-After is the gateway saying "too fast this second", not
  the lab asking for a pause: the router waits a moment, repeats the same call and carries on, and never pauses the
  monitor for it. Only a 503, or a 429 that carries a Retry-After, pauses the monitor, until the time the lab named.

  Background:
    Given a router with three stories whose lab jobs are still running

  Scenario: Lab calls leave at most four a second
    When the router makes eight lab calls in a row
    Then no two calls left less than a quarter of a second apart
    And no second of the clock saw more than four calls

  Scenario: A bare 429 is retried after a short wait and the run continues
    Given the gateway answers "Too Many Requests" twice and then the lab recovers
    When the collector asks the lab about the jobs through the paced client
    Then the same calls were repeated after waiting about a second each time
    And the monitor is not paused and the stories are delivered

  Scenario: A 503 with Retry-After pauses the monitor until then
    Given the lab answers 503 and asks the router to wait forty-five seconds
    When the collector asks the lab about the jobs through the paced client
    Then the monitor records that the lab is paused for forty-five seconds

  Scenario: An old 429 back-off row is cleared
    Given the monitor still carries a pause caused by a 429 with no Retry-After
    When the collector asks the lab about the jobs through the paced client
    Then the lab was called and the old pause row is gone
