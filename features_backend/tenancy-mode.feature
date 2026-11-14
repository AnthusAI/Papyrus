Feature: Tenancy mode
  One synth-time setting says whether a backend is a dedicated stack (one site,
  the default) or a shared stack (several tenants). Functions learn it from one
  environment variable, read only through one helper in Python and in TypeScript.

  Scenario: An existing site synthesises exactly as before
    Given a site config with no tenancy setting
    When the backend is synthesised
    Then the template is identical to the previous release's

  Scenario: Functions on a shared stack know it
    Given tenancy mode "shared"
    When content-actions starts
    Then the tenancy helper reports shared in Python and in TypeScript

  Scenario: A mistyped mode is refused
    Given tenancy mode "pooled"
    When the backend is synthesised
    Then synthesis fails naming tenancy.mode
