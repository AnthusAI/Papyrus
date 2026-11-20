Feature: A monitor can run at a fixed time of day
  A monitor's pass starts at the interval after the last one, which drifts by the length of the pass and the schedule's
  five minute grain. A monitor whose config has runAt, a wall-clock time and an IANA time zone such as 02:00 in
  America/New_York, starts each pass at the next occurrence of that time instead, whatever the length of the day. The
  five minute wake stays: a pass stopped by its time budget is due at once and resumes on the next wake, and only a finished
  pass waits for the next occurrence of the time.

  Scenario: The next run is the next occurrence of the time
    Given a monitor with runAt 02:00 in America/New_York
    When a pass finishes at 02:03 on the 28th
    Then the monitor is next due at 02:00 on the 29th, not at 02:03
    And a pass finishing at 01:30 would be next due at 02:00 the same morning

  Scenario: Falling back keeps 02:00 on the clock
    Given a monitor with runAt 02:00 in America/New_York
    When a pass finishes at 02:07 on 31 October 2026, the day before the clocks go back
    Then the monitor is next due at 02:00 on 1 November, twenty five hours later
    And after that pass it is next due at 02:00 on 2 November

  Scenario: Springing forward runs at the first moment after the missing hour
    Given a monitor with runAt 02:00 in America/New_York
    When a pass finishes on 7 March 2026, the day before the clocks go forward
    Then the monitor is next due at 03:00 Eastern on the 8th, which is 07:00 UTC, because 02:00 does not exist that day
    And the day after it is due at 02:00 again

  Scenario: A wake a moment early does not run the morning twice
    Given a monitor with runAt 02:00 whose next due time is 02:00
    When the schedule wakes it thirty seconds before 02:00 and it finishes
    Then it is next due at 02:00 the following day, not at 02:00 that morning

  Scenario: A pass stopped by its time budget resumes on the next wake and then waits for the time
    Given a monitor with runAt 02:00 whose pass starts at 02:03 and runs out of time
    Then it is due at once, and the five minute wake continues the pass at 02:08
    And the continued pass asks no search the first run already asked
    When the continued pass finishes
    Then the monitor is next due at 02:00 the following day

  Scenario: A runAt that cannot be read is refused
    Given a monitor config whose runAt has an hour of 25, an unknown time zone, an extra field or is not an object
    When the config is validated
    Then it is refused, and a config without runAt behaves as before, due an interval after each pass
