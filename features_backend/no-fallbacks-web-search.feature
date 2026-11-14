Feature: Web search providers are named in one place
  The search providers form an ordered chain that an operator names in WEB_SEARCH_PROVIDERS. The older single-provider name
  WEB_SEARCH_PROVIDER also worked, so a machine could be configured in two places and the chain could differ from what an operator
  thought they had set. The old name is no longer read: setting it is an error that tells the operator which setting to use.

  Scenario: The chain comes from WEB_SEARCH_PROVIDERS
    Given WEB_SEARCH_PROVIDERS names two providers
    When the provider chain is resolved
    Then the chain is those two providers in order

  Scenario: The retired single provider name is an error that names its replacement
    Given only the retired WEB_SEARCH_PROVIDER is set
    When the provider chain is resolved
    Then resolution fails and the error names WEB_SEARCH_PROVIDERS
