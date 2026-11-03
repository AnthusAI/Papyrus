@backend @monitoring-suggest-backlog
Feature: The router's hourly suggest-backlog task writes suggestions from the vectors that exist, with no indexing and no embeddings
  A site with thousands of References, such as Machines on Machines with about 1,400 accepted and 6,700 pending, cannot get its suggestions written by the daily
  monitor-stories run alone: the vector pass is held to the first quarter of that run's time, and the time that is left after listing the plan goes to a few
  hundred suggestions a day. So the router has a task of its own, suggest-backlog, run every hour by the scheduler. Like the monitor-stories and auto-accept tasks it
  runs once per publication, each in its own invocation with the Lambda's whole time budget and its own lock, so one publication's run never holds up another's or the
  routing pass. A run with no publication named only starts those runs, for the publications that have a vector index and suggestions on.
  The task does what the daily pass does first and nothing else: it suggests related References and concepts for the References that already have a summary vector,
  in the order an editor looks at the site (a person's signal first, then pending, then the rest, newest first), from the same saved place, so the daily run and
  the hourly task go on from each other's progress. It lists no index, embeds nothing, reads no model key and asks no model: it spends on S3 Vectors reads and queries
  and on the publication's own API, and its cost is always zero. A Reference with no vector yet is remembered as owed to the daily index sync. There is no fixed number
  of suggestions: the run goes on until the Lambda's time, less two minutes to finish, is spent, and the log line says how many suggestions it wrote, how many are
  left and how long each step took, so the next hour's progress can be read from the logs. The index, the backends and the clock are fakes in these scenarios.

  Scenario: With no publication named the task only starts one run for each publication that has an index and suggestions on
    Given a router with five publications, two of which have a vector index and suggestions on
    When the router runs the suggest-backlog task without naming a publication
    Then it started one run for each of those two publications
    And the fan-out took no lock and wrote no receipt

  Scenario: A run suggests in order from the saved place, with no sync, no embedding and no cost, and logs its progress
    Given a suggest-backlog publication with an index and a storage bucket
    And 3 accepted References, one of which has no summary vector yet
    When the router runs the suggest-backlog task for that publication
    Then suggestions were made for the 3 References, the newest first
    And the index was not synced and nothing was embedded
    And the log line says 4 suggestions written, 1 suggestion left and 1 awaiting the index
    And the log line says the cost was 0 and gives the seconds of each step
    And the router's table holds the saved place and the Reference that is owed to the index

  Scenario: A run stops with the time to finish left and the next hour goes on from the saved place
    Given a suggest-backlog publication with an index and a storage bucket
    And 5 accepted References
    And each suggestion takes 150 of the run's 600 seconds
    When the router runs the suggest-backlog task for that publication
    Then the run was stopped by time with 1 suggestion left
    When an hour later the router runs the suggest-backlog task for that publication
    Then the log line says no suggestions are left
    And every Reference was suggested for once

  Scenario: One publication's run does not block routing or another publication's run
    Given a suggest-backlog publication with an index and a storage bucket
    And the suggest-backlog run of that publication is in progress
    When the router runs the suggest-backlog task for that publication
    Then the suggest-backlog run reports that it is locked
    And the routing pass lock is free
    And the monitor-stories lock of that publication is free

  Scenario: A publication the monitor does not list is refused
    Given a suggest-backlog publication with an index and a storage bucket
    When the router runs the suggest-backlog task for a publication the monitor does not list
    Then the suggest-backlog run is refused as an unknown publication and does nothing

  Scenario: A publication without a vector index is skipped and writes nothing
    Given a suggest-backlog publication with no index
    When the router runs the suggest-backlog task for that publication
    Then nothing was suggested and the log line says the publication was skipped

  Scenario: The stack schedules the task every hour for the shared monitor and for Distinctive Mark and adds no permission
    Given the monitoring stack template
    Then the stack has an hourly suggest-backlog schedule for the hn monitor and one for the web-distinctive monitor
    And neither suggest-backlog schedule retries a failed run
    And the schedules do not start in the ten minutes after the daily monitor-stories run
    And the router role needs no new permission for the task
