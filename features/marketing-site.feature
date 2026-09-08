@marketing-site
Feature: Standalone Papyrus marketing site
  The public Papyrus explanation lives apart from the CMS reader.

  Scenario: The marketing foundation is independently runnable
    Given the Papyrus marketing site foundation is present
    Then it should use its own development command
    And it should be configured for static hosting
    And it should include the Papyrus plant pictogram
    And it should identify papyrus.anth.us as its intended public home
