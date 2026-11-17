Feature: A deferred monitor item is retried under its own wake key
  An item the router defers at an automation's limit keeps its row, and a later sweep starts it. The runner refuses a
  run that has no well-formed wake key, so a retry that sent the stored request as it was would lose every item that
  was deferred before wake keys existed: the row is never picked up again. The router therefore builds the wake key
  from the row on every retry, in the same form the first start would have used: the automation (or the procedure when
  no automation governs it), the Reference, and the fact that it is a new Reference. A key stored on the row is never
  trusted. The retry is the same wake as the first attempt, so it can never start a second run. A row that has not
  got what a key needs is marked with the reason and counted as a failed start; it is never guessed at and never lost
  without a trace.

  Background:
    Given the TTAB monitor delivers three new decisions
    And the site has the TTAB automation with room for 1 at a time

  Scenario: An item deferred before wake keys starts once on the next sweep
    Given the router sweeps and defers two decisions
    And the deferred rows were stored before wake keys, with no key on their requests
    When the running procedure finishes and the router sweeps
    Then 1 deferred item starts
    And its request carries the wake key built from its row
    And that row says started
    When the running procedure finishes and the router sweeps
    Then the other deferred item starts, and no item has started twice

  Scenario: A retried item uses the same key as its first attempt
    Given the router sweeps and defers two decisions
    When the running procedure finishes and the router sweeps
    Then 1 deferred item starts
    And its request carries the same wake key its deferred row was stored with

  Scenario: A row with a stored key that differs from the row's own gets the row's key
    Given the router sweeps and defers two decisions
    And the deferred rows carry a wake key for some other Reference
    When the running procedure finishes and the router sweeps
    Then 1 deferred item starts
    And its request carries the wake key built from its row
    And its row now holds the key it started with

  Scenario: A deferred item whose first run already exists does not run again
    Given the router sweeps and defers two decisions
    And the deferred rows were stored before wake keys, with no key on their requests
    And the first attempt of the first deferred item already made its run record
    When the running procedure finishes and the router sweeps
    Then 1 deferred item starts
    And the runner reports it as a duplicate of the run that exists
    And the site holds 1 run record for it

  Scenario: A row that cannot give a wake key is reported, not lost silently
    Given the router sweeps and defers two decisions
    And the deferred rows have lost their Reference id
    When the running procedure finishes and the router sweeps
    Then no deferred item starts
    And 2 rows say startFailed and name the missing Reference id as the reason
    And the sweep counts 2 failed starts
