Feature: A site owns the whole text of its figure rules
  Papyrus ships general figure rules that name roles and no brand. A site whose pictures follow different rules, for example one where no generated
  image ever shows a real person, saves its own figure rules as a guideline document with one field, the complete text. A site's rules replace the general
  ones for that site and nothing is merged, so what a person or an agent reads is one text and the command says whose it is. A site that saved nothing
  reads the general rules. Image prompts are built only from the site's own image profile, never from this text.

  Scenario: A site that saved no figure rules reads the general rules
    Given a site that has saved no figure rules
    When the figure rules are read
    Then they are the packaged general rules
    And they are reported as the packaged default

  Scenario: A site's own figure rules replace the general rules whole
    Given a site that saved the figure rules "No generated image shows a real person."
    When the figure rules are read
    Then the text is exactly "No generated image shows a real person."
    And they are reported as the site's own, at version 1
    And none of the packaged general rules is in the text

  Scenario: Another site's figure rules are never read
    Given a site that saved the figure rules "No generated image shows a real person."
    And a second site with its own backend that saved no figure rules
    When the second site's figure rules are read
    Then they are the packaged general rules

  Scenario: Empty figure rules are refused when saved
    Given a site that has saved no figure rules
    When an admin saves figure rules with no text
    Then the save is refused naming bodyMarkus

  Scenario: The command prints the packaged rules on request
    Given a site that saved the figure rules "No generated image shows a real person."
    When the figure rules command is run with the packaged flag
    Then it prints the packaged general rules and does not look at the site

  Scenario: A site that cannot be read never gets the general rules in place of its own
    When the figure rules command is run and the site cannot be reached
    Then it fails saying the site's figure rules could not be read
