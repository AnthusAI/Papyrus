Feature: Adopting an automation onto a standing responsibility
  An automation that ran before the agent policy existed starts no run once the runner enforces the policy, until a person adopts it:
  names the one responsibility it fills. Adoption is data on the Automation record. It is set by an admin who is a person and is never
  inferred from the procedure or the trigger. It sets no rung: the rung stays a separate admin action in the agent policy, so adopting
  never starts a run and never lifts a pause.

  Background:
    Given a site with the automation "distinctive.ttab" and no agent policy

  Scenario: A dry run says what would change and writes nothing
    When an admin adopts "distinctive.ttab" as "accept" with a dry run
    Then the result says it would adopt "distinctive.ttab" as "accept"
    And the automation has no responsibility

  Scenario: An admin adopts an automation
    When an admin adopts "distinctive.ttab" as "accept"
    Then the automation's responsibility is "accept"
    And the agent policy is still version 0

  Scenario: Adopting again with the same responsibility changes nothing
    Given "distinctive.ttab" is adopted as "accept"
    When an admin adopts "distinctive.ttab" as "accept"
    Then the result says there is nothing to change

  Scenario: An automation adopted as one responsibility is not changed to another
    Given "distinctive.ttab" is adopted as "accept"
    When an admin adopts "distinctive.ttab" as "rate"
    Then the adoption is refused saying it is already adopted as "accept"
    And the automation's responsibility is "accept"

  Scenario: An editor cannot adopt
    When an editor adopts "distinctive.ttab" as "accept"
    Then the adoption is refused saying only an admin who is a person adopts
    And the automation has no responsibility

  Scenario: An agent cannot adopt, even with an admin's session
    When an agent adopts "distinctive.ttab" as "accept"
    Then the adoption is refused saying only an admin who is a person adopts
    And the automation has no responsibility

  Scenario: A name that is not a responsibility is refused
    When an admin adopts "distinctive.ttab" as "do_everything"
    Then the adoption is refused saying "do_everything" is not a responsibility

  Scenario: An automation that does not exist is refused
    When an admin adopts "no.such.automation" as "accept"
    Then the adoption is refused saying automation no.such.automation does not exist

  Scenario: Updating an adopted automation keeps its responsibility
    Given "distinctive.ttab" is adopted as "accept"
    When an admin changes the title of "distinctive.ttab"
    Then the automation's responsibility is "accept"
