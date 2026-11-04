Feature: An alarm says when Cyclotron decisions stop while items are waiting
  On 2026-11-03 one stuck job blocked the shared Cyclotron run. Decisions stopped for about twelve hours, thousands of jobs
  queued, and nothing raised an alarm because every router pass finished without an error. The router logs one summary per pass
  with how many decisions it recorded and how many jobs were still waiting. Two metric filters turn those into metrics, and one
  alarm breaches in an hour when nothing was decided while something was waiting. It fires after two such hours in a row, summed
  across every monitor. A quiet system, a single quiet hour and a router that logs nothing at all do not make it fire.

  Scenario: The template counts decisions and waiting jobs from the router log and alarms on the two together
    Given the monitoring stack template for the decisions-stopped alarm
    Then a metric filter on the router log group makes "RouterDecided" from "counts.decided" in the "Papyrus/Monitoring" namespace
    And a metric filter on the router log group makes "RouterAwaiting" from "counts.awaiting" in the "Papyrus/Monitoring" namespace
    And "papyrus-monitoring-decisions-stopped" alarms when decided is 0 and awaiting is above 0, for 2 of 2 hourly periods
    And missing data does not breach the alarm

  Scenario: The alarm sends an email, and the address is not in the repository
    Given the monitoring stack template for the decisions-stopped alarm
    Then the alarm notifies one topic
    And that topic has one subscription, by email, to an address read from an SSM parameter
    And the template contains no email address

  Scenario: A quiet system with nothing waiting never alarms
    Given the hourly router totals of a quiet night
    When the alarm is evaluated over those hours
    Then it never fires

  Scenario: One hour without decisions while items wait does not alarm
    Given the hourly router totals of 2026-11-02, when one hour had ten jobs waiting and no decisions
    When the alarm is evaluated over those hours
    Then it never fires

  Scenario: The stoppage of 2026-11-03 alarms while it is still going on
    Given the hourly router totals of 2026-11-03, when the last decision was recorded at 16:28 UTC
    When the alarm is evaluated over those hours
    Then it first fires in the 18:00 UTC hour, about two hours after the last decision
    And it keeps firing until decisions return

  Scenario: A router that logs nothing does not alarm
    Given two hours in which the router logged nothing
    When the alarm is evaluated over those hours
    Then it never fires
