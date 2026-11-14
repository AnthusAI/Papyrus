Feature: A failed Amplify build is read before anything is retried
  Amplify builds cost money by the minute, and a blind retry of the same commit repeats the same failure for
  another twelve minutes. The operator therefore reads the failed job's real error first. The command
  papyrus-infra amplify job-log fetches the job, prints each step's status, the tail of the failed step's log and
  the first error in it, and the failed CloudFormation stack events recorded since the job started. It only reads.

  Scenario: A failed job's log is printed with its first error
    Given a failed Amplify job whose build log ends with an out of memory error
    When the operator asks for the job log of the latest failed job
    Then every step of the job is listed with its status
    And the tail of the build log is printed
    And the cause names the out of memory line and its line number

  Scenario: A deploy error from the stack is named as the cause
    Given a failed Amplify job whose backend stack rejected an unknown plugin
    When the operator asks for the job log of the latest failed job
    Then the cause names the failed custom resource and its message
    And the first error of the build log is still shown
    And failures from before the job started are not reported

  Scenario: A missing module in the build log is named as the cause
    Given a failed Amplify job whose build log reports a missing Python module
    When the operator asks for the job log of the latest failed job
    Then the cause names the missing module

  Scenario: The application id is required
    When the operator asks for a job log without an application id
    Then the command fails and says the application id is required
