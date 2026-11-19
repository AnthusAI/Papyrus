@brand-agnostic
Feature: A site names the parameter that holds the model key its agents' runs use
  A change feed puts a wake on the site's queue for each agent that listens for a change, and the runner that takes the wake runs the agent's procedure. The run needs a
  model key, and the wake carries the NAME of the SSM parameter that holds it. A name is not a secret: a site sets it in its backend configuration as
  `agents.openAiKeyParameter`, and the two feed functions pass it on in `PAPYRUS_OPENAI_KEY_PARAMETER`. The deploy never reads, prints or stores the key. The feeds hold
  no right to the key; the runner reads the one named parameter with `ssm:GetParameter` alone. The key is a SecureString under the account's AWS-managed key, so nothing
  needs `kms:Decrypt`. A site that names no parameter has runs with no key, and they fail closed with "The run has no model key": there is no fallback key. Naming the
  parameter adds no resource, so a new site's first deploy does not move.

  Scenario: A site that names the parameter puts it on both feed functions
    Given the agent pieces of the site backend
    When the agents stack is priced
    Then the Item change feed and the change feed each name the model key's parameter
    And naming the parameter adds no resource to either feed

  Scenario: A site that names no parameter sets none
    Given the agent pieces of the site backend
    When the agents stack is priced
    Then a feed with no parameter named carries no model key setting

  Scenario: The feeds never hold a right to the key
    Given the agent pieces of the site backend
    When the agents stack is priced
    Then neither feed's policy holds any ssm or kms action

  Scenario: The runner may read the one named parameter and nothing else
    Given the agent pieces of the site backend
    When the agents stack is priced
    Then the runner's role holds ssm:GetParameter alone on the one parameter

  Scenario: A setting that is not a parameter name is refused before any deploy
    Then a key, a path, an empty value and a name without a leading slash are refused as the model key parameter
