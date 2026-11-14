Feature: A page re-render reports how it really ended
  Re-rendering a page can take longer than the thirty seconds AppSync gives a
  request, so a command that waited inside one call used to print "Execution
  timed out" or "The read operation timed out" although the site finished the
  work. A re-render is now a job, like a publish: the command starts it, is
  answered at once with a job, and asks about the job in short calls until it
  has ended or its wait is over. It then says one of three things: the
  re-render is done, it failed and why, or it is still running, which is not a
  failure, with the command that checks on it later. A request that got no
  answer at all is reported as not known, never as failed. The re-render that
  the link commands start after writing a link reports in the same way, and a
  link that was saved stays saved.

  Scenario: A re-render that outlasts the first call is followed to its end
    Given a re-render that is still running when the command first asks and done a moment later
    When the editor re-renders the Story with no purge
    Then the re-render command exits with code 0
    And the command says the re-render wrote 1 pages
    And the command asked about the job until it was done

  Scenario: A re-render that is still running when the wait is over is not a failure
    Given a re-render that keeps running past the command's wait
    When the editor re-renders the Story with no purge
    Then the re-render command exits with code 5
    And the command says the re-render is still running and not failed
    And the command names the command that checks on it

  Scenario: Checking on a re-render later says how it ended
    Given a re-render that has finished
    When the editor asks how the re-render of the Story stands
    Then the re-render command exits with code 0
    And the command says the re-render wrote 1 pages

  Scenario: A re-render that fails says why
    Given a re-render whose job fails with the reason "the hook raised"
    When the editor re-renders the Story with no purge
    Then the re-render command exits with code 1
    And the command says the re-render failed with the reason "the hook raised"

  Scenario: A request that gets no answer is not known, not failed
    Given a newsroom that does not answer the request to start the re-render
    When the editor re-renders the Story with no purge
    Then the re-render command exits with code 5
    And the command says the outcome is not known and not failed

  Scenario: The server starts the re-render in the background and keeps a job
    Given a site that keeps job records
    When the editor asks the newsroom to re-render the Story in the background
    Then the answer names a job that is queued
    And nothing was rendered inside the call
    And the same request again joins that job

  Scenario: The job ends done with what it wrote
    Given a site that keeps job records
    And the editor asked the newsroom to re-render the Story in the background
    When the scheduled re-render runs
    Then asking for the job's status says it is done and that it wrote 1 pages

  Scenario: The job ends failed with the reason when the render fails
    Given a site that keeps job records
    And the editor asked the newsroom to re-render the Story in the background
    When the scheduled re-render runs and the render fails with "the hook raised"
    Then asking for the job's status says it failed with the reason "the hook raised"

  Scenario: The re-render after a link reports a job that is still running without failing the link
    Given a re-render that keeps running past the command's wait
    When a link between two Stories is saved and their pages are re-rendered
    Then the link stays saved
    And the warning says the re-render is not confirmed and is not a failure
    And the warning names the command that checks on it
