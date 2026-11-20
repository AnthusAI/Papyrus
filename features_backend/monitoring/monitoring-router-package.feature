Feature: The router package carries the editorial gate's dependencies
  The router Lambda drafts ideas from monitored stories and checks each against the publication's policies with Humanus. The Lambda
  has boto3 and nothing else, so the router package has to hold Humanus and the Jev judgment client with everything they import,
  built as binary wheels for the function's platform at the versions poetry.lock pins. Without them the task fails on every site
  with a missing module, which the tests that import only the drafting do not see.

  Scenario: The package holds the gate, Humanus and the Jev client and runs a rules check by itself
    Given the router package built from this repository
    When the package is unpacked as the Lambda does and its gate is imported by an isolated interpreter
    Then Humanus and the Jev client load from the package alone
    And a rules-lane check of a sentence with a banned phrase returns one finding

  Scenario: The wheels are the locked dependency closure
    Given the router package built from this repository
    Then the wheels are the poetry.lock closure of Humanus and the Jev client
    And every wheel the Lambda build downloads is checked against its poetry.lock hash
