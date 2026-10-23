@brand-agnostic
Feature: The data API stays inside the CloudFormation stack limit
  Every Lambda-backed query and mutation of a site's data API adds resources to
  one Amplify nested stack, and CloudFormation refuses a stack of more than 500
  resources. Fields that call the same Lambda share one AppSync data source, so
  adding a field costs one resolver and a backend deploy keeps working as the
  API grows.

  Scenario: A site with every plugin deploys with room to spare
    Given the site backend is synthesized with every plugin enabled
    Then the Lambda resolver stack has fewer than 450 resources
    And fields that call the same Lambda share one data source
