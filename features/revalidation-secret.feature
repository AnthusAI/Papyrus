@brand-agnostic
Feature: Secret-safe on-demand revalidation
  A Pretext publish refreshes live pages through POST /api/revalidate. The shared
  secret is an SSM SecureString read at runtime by the route and by content-actions;
  site.json, Git and branch variables never hold it. These scenarios are verified by
  scripts/test-revalidate-secret.ts (npm run test:revalidate-secret), the Python
  reader revalidation tests and npm run test:infra-synth.

  Scenario: The route authorizes only the secret stored in the named SSM parameter
    Given PAPYRUS_REVALIDATE_SECRET_PARAMETER names an SSM parameter
    Then a request carrying that parameter's value is authorized
    And a request with a different or missing value is rejected

  Scenario: The route fails closed
    Given the parameter is unset, empty or unreadable
    Then every request is rejected and no secret detail is logged

  Scenario: A secret environment variable is not a secret source
    Given PAPYRUS_REVALIDATE_SECRET is set as a variable
    Then it is ignored by the route and by content-actions

  Scenario: The template grants one parameter read to a Pretext site
    Given a Pretext site.json
    Then the compute role may call ssm:GetParameter only on its revalidate parameter
    And markus-static sites receive no SSM grant
