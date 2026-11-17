Feature: The once-only create is proved on a real site with one command
  The newsroom function makes a run's record from the wake key and refuses a second record for the same key. A fake
  backend cannot show that the real data API refuses it the way the function expects, so a signed-in person runs
  `papyrus procedures check-wake-guard` against a site. It starts one wake key twice, requires the second answer to
  be a duplicate of the first run, and finishes the record it made as a run that did nothing, so no procedure runs and
  no record stays started. The wake key belongs to the check alone.

  Background:
    Given a site backend that answers the start as the newsroom function does

  Scenario: The second start of the same key is a duplicate of the first
    When the wake guard check runs for the procedure "newsroom.fact-check"
    Then the check is proved
    And the site holds 1 run record
    And the record is finished as nothing to do with the reason "wake_guard_check"
    And no procedure was loaded or run

  Scenario: A dry run writes nothing
    When the wake guard check is previewed for the procedure "newsroom.fact-check"
    Then the check shows its wake key and made no request

  Scenario: A site that makes a second record is reported, and the record is still finished
    Given the site backend ignores the once-only condition
    When the wake guard check runs for the procedure "newsroom.fact-check"
    Then the check fails because the second answer was not a duplicate
    And the first record is finished as nothing to do with the reason "wake_guard_check"

  Scenario: A request id that is not recognisable as a check is refused
    When the wake guard check runs with the request id "request-41"
    Then the check is refused for its request id
    And the site holds 0 run records
