Feature: Independently authored language companions
  A publication can tell a subject differently in each language without pretending
  that independently reported copy is a translation. Editorial review still applies.

  Scenario: Different sources and structure survive as an unpublished companion
    Given an original article and independently authored Spanish copy
    When the editor imports the independently authored edition
    Then the companion preserves its own copy and sources without translation alignment
    And the original article is unchanged and the companion is unpublished

  Scenario: Existing translations are never silently replaced
    Given an original article and independently authored Spanish copy
    And that language already has a translation
    When the editor imports the independently authored edition
    Then the authored import is refused without a write

  Scenario: Translation work cannot overwrite an authored companion
    Given an original article and independently authored Spanish copy
    When the editor imports the independently authored edition
    Then a translation request for that language is refused

  Scenario: A queued translation is a conflict, not permission to replace
    Given an original article and independently authored Spanish copy
    And a translation for that language is queued
    When the editor imports the independently authored edition
    Then the queued translation conflict saves nothing

  Scenario: Importing the same authored copy twice is idempotent
    Given an original article and independently authored Spanish copy
    When the editor imports the independently authored edition
    And the editor imports the independently authored edition
    Then only one unpublished authored version exists

  Scenario: A different tenant cannot be used as an original
    Given an original article and independently authored Spanish copy
    And the original belongs to a different tenant
    When the editor imports the independently authored edition
    Then the cross-tenant import is refused

  Scenario: A dry run never stages a companion
    Given an original article and independently authored Spanish copy
    And the import is only a dry run
    When the editor imports the independently authored edition
    Then no companion or translation request is written

  Scenario: An authored companion requires its own editorial checklist
    Given an original article and independently authored Spanish copy
    When the editor imports the independently authored edition
    Then publishing the companion refuses an open editorial checklist

  Scenario: Reader output does not misidentify original copy as a translation
    Given an original article and independently authored Spanish copy
    When the editor imports the independently authored edition
    Then the reader metadata identifies independent authorship without a translator notice
