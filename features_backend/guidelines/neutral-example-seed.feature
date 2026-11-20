@backend @newsroom
Feature: The bundled example mission and sections belong to no publication
  As the owner of a new site
  I need the files a fresh site is seeded from to be neutral
  So that my newsroom never starts with another publication's mission or sections.

  Scenario: The default example files name no publication and no subject area
    Given the bundled example mission, policy and sections
    Then none of them names a publication or a security subject
    And the sections are neutral news, analysis and explainer sections

  Scenario: The Threat Intelligence publication's own files are imports, not defaults
    Given the Threat Intelligence mission, policy and sections
    Then they are separate files from the bundled example files
    And the command line default for sections and doctrine is the neutral example
