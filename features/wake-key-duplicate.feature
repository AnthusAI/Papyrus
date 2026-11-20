Feature: A wake that already has its run is answered as a duplicate, and nothing else is
  The newsroom function makes a run's record with an id derived from the wake key and a condition that no
  record with that id exists. When the data API refuses that create, the function must tell a refusal for an
  existing record from every other failure. It recognises the refusal by its error type, the conditional-check
  failure the data API names for an existing id, or by its text, including when either is nested inside another
  error. An answer it does not recognise is thrown as a failed start: a duplicate then fails falsely, but it never
  runs twice. These scenarios call the function's handler for startNewsroomProcedureRun, not a helper.

  Background:
    Given a site whose procedure "newsroom.fact-check" is published
    And the wake "fact-check|story-1|v7|story.stage_entered" already has its run record

  Scenario: A create refused with the conditional-check error type answers duplicate
    Given the data API refuses the create with the error type "DynamoDB:ConditionalCheckFailedException" and a message it has not used before
    When the wake "fact-check|story-1|v7|story.stage_entered" is started
    Then the answer is a duplicate of the first run
    And the site still holds 1 run record

  Scenario: A create refused with the old text answers duplicate
    Given the data API refuses the create with the message "The conditional request failed"
    When the wake "fact-check|story-1|v7|story.stage_entered" is started
    Then the answer is a duplicate of the first run
    And the site still holds 1 run record

  Scenario: A conditional-check refusal nested inside another error answers duplicate
    Given the data API refuses the create with the error "Request failed" that holds the error type "DynamoDB:ConditionalCheckFailedException"
    When the wake "fact-check|story-1|v7|story.stage_entered" is started
    Then the answer is a duplicate of the first run

  Scenario Outline: Any other create error is thrown
    Given the data API refuses the create with the error type "<type>" and the message "<message>"
    When the wake "fact-check|story-1|v7|story.stage_entered" is started
    Then the start fails with "create ProcedureRun failed"
    And the site still holds 1 run record

    Examples:
      | type                                              | message                  |
      | DynamoDB:ProvisionedThroughputExceededException   | The rate was exceeded    |
      | Unauthorized                                      | Not authorized to access |
      | (none)                                            | Something else happened  |

  Scenario: A new wake is created and not reported as a duplicate
    When the wake "fact-check|story-1|v8|story.stage_entered" is started
    Then the answer says a run was created
    And the site holds 2 run records
