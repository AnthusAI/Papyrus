@backend @newsroom
Feature: A definition names a model tier and the site's policy names the model (slice G4, PPY-c9c165)
  An agent's definition says which tier its work is: editorial, work, bulk or decision. It never names a model. The site's agent policy maps each tier to a
  model id, and a tier the site has not mapped uses the engine's default for it. Changing a model is a new version of the policy, read by the next run with
  no deploy. A model the price table does not list is refused when the policy is saved, so a run's cost is never counted as free. A tier with no model at all
  (the decision tier before a site maps it) is an error that names the tier.

  Scenario: A tier the site has not mapped uses the engine's default
    Given a site that has never saved an agent policy
    Then the "bulk" tier uses "gpt-6-luna"

  Scenario: The decision tier has no engine default
    Given a site that has never saved an agent policy
    Then the "decision" tier has no model and the error names the tier

  Scenario: Changing a tier's model in the policy changes the next run's model
    Given a site that has never saved an agent policy
    When an admin maps the "bulk" tier to "gpt-6-luna-2026-09-01" because "Pin the dated release"
    Then the policy is version 1
    And the "bulk" tier uses "gpt-6-luna-2026-09-01"

  Scenario: A model the price table does not list is refused when saved
    Given a site that has never saved an agent policy
    When an admin maps the "bulk" tier to "model-without-a-price" because "Try a new model"
    Then the change is refused as invalid
    And the refusal mentions "model-without-a-price"
    And the policy is version 0

  Scenario: The rating agent's model call uses its tier's model and the run records both
    Given a site that maps the "bulk" tier to "gpt-6-luna-2026-09-01"
    When the rating agent judges one Story under that policy
    Then the model call was made with "gpt-6-luna-2026-09-01"
    And the run's usage records the tier "bulk" and the model "gpt-6-luna-2026-09-01"
