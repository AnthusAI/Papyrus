Feature: Backend features run side by side on every processor
  Ryan asked whether parts of the suite could run in parallel to shorten a CI run. The backend features were the longest job in
  every run, and each one builds its own world, so a shard now runs its feature files in one behave process per processor of
  the runner. These scenarios are checked by procedures/newsroom/tests/test_behave_side_by_side.py and
  procedures/newsroom/tests/test_step_registry_indexed_by_opening_words.py.

  Scenario: Every feature file runs exactly once
    Given a shard's list of feature files
    When the files are dealt out to one process per processor
    Then together the processes run every file in the list, none dropped and none repeated

  Scenario: One failing process fails the shard
    Given one process reports a failing scenario
    Then the shard fails and that process's output is printed again at the end of the log

  Scenario: The log still reads one process after another
    When the processes finish
    Then each process's output is printed whole, in its own group, and never mixed with another's

  Scenario: An empty list is a failure
    Given no feature files reach the runner
    Then the shard fails, so a broken file list can never pass quietly

  Scenario: A run no longer spends half a minute finding its steps
    Given about fifteen thousand step definitions
    When behave loads them and looks one up for each step
    Then only the definitions that share the step's opening words are tried
    And every step finds the same definition stock behave finds, and an ambiguous definition is still refused

  Scenario: No shard is left holding all the slow features
    Given a list of how many seconds each slow feature takes
    When the feature files are dealt out to the shards and to the processes of a shard
    Then the slowest go first and each goes to whoever has the least so far
    And the shards together still run every backend feature exactly once

  Scenario: Every Python job restores only the virtual environment
    Given poetry's download folders are left out of the cache
    Then a job restores about a third of what it restored before and installs nothing new
