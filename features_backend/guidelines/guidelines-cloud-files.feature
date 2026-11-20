Feature: Writing guidelines are stored in the cloud as the same guideline files a person keeps in a folder
  A site's writing guidelines for the publication, a section or a language are a set of guideline files: one folder for each guideline, each with a GUIDELINE.md. The
  cloud stores the files themselves, with the catalog row holding only the version, who saved it, when, why and one hash over the whole set. papyrus guidelines save
  --kind writing --dir DIR stores a folder as the next version and refuses it as stale when the version it names is no longer current; papyrus guidelines export
  --dir DIR writes the files back byte for byte, so a guideline written on a laptop, checked there and saved to a site is the same bytes at every step. The
  structured fields (voice, audience, tone, lexicon, glossary, headline, binding rules and the rest) are guideline files with fixed names, the kebab-case name of
  the field; the console still saves those fields, and the server turns them into those files and keeps every rule file already in the set. A set is valid or
  refused whole, and a file that says it belongs to another scope or language than the set it is saved into is refused. Only one set of files is ever stored.

  Background:
    Given a site with no writing guidelines yet

  Scenario: A folder of guideline files is saved as a version and exported byte for byte
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    When an admin saves the folder with the reason "First files"
    Then the writing guidelines are at version 1 with one stored file for each file of the folder
    And exporting the writing guidelines to a new folder gives every file byte for byte as it was in the folder
    And the catalog row holds the hash over the set and no text

  Scenario: A stale version is refused and nothing is stored
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    And the folder is saved as the first version
    When an admin saves a changed folder naming "none" as the version it replaces
    Then the save of the folder is refused as stale
    And the folder's writing guidelines are still at version 1

  Scenario: Saving the same folder again makes no new version
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    And the folder is saved as the first version
    When an admin saves the same folder again naming the current version
    Then the folder's writing guidelines are still at version 1

  Scenario Outline: A set with a problem is refused whole and nothing is stored
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    And the folder has <problem>
    When an admin saves the folder with the reason "Bad files"
    Then the save is refused naming the guideline "<guideline>" and the code "<code>"
    And nothing is stored from the folder

    Examples:
      | problem                                                  | guideline    | code           |
      | a rule with the unknown key "voice"                      | plain-claims | unknown_key    |
      | a rule written for the scope section/news                | plain-claims | wrong_lineage  |
      | a rule written for the language es                       | plain-claims | wrong_lineage  |
      | a rule of the kind image                                 | plain-claims | invalid_value  |
      | a tone file whose body is not a list of lines            | tone         | invalid_body   |
      | a tone file with the severity error                      | tone         | invalid_value  |
      | a second rule with the id of the first                   | twin         | duplicate_id   |
      | a file outside any guideline folder                      | stray.md     | stray_file     |

  Scenario Outline: A field of the writing document is a file with a fixed name
    When an admin saves the structured field <field> through the console
    Then the stored files include "<name>/GUIDELINE.md" with the severity guidance
    And reading the writing guidelines gives the field <field> exactly as it was saved

    Examples:
      | field         | name           |
      | tone          | tone           |
      | voicePatterns | voice-patterns |
      | editorialAim  | editorial-aim  |
      | bodyMarkus    | body-markus    |
      | lexicon       | lexicon        |
      | glossary      | glossary       |
      | headline      | headline       |
      | constraints   | constraints    |
      | voice         | voice          |

  Scenario: Saving the structured fields keeps the rule files of the set
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    And the folder is saved as the first version
    When an admin changes the structured tone to "Brisk." through the console
    Then the writing guidelines are at version 2
    And the rule file "plain-claims" is stored exactly as it was
    And the stored tone reads "Brisk."

  Scenario: A section and a language are sets of their own
    Given a folder with the tone "Warm." and the rule "plain-claims" at severity error that avoids "we believe"
    And the folder is saved as the first version
    When an admin saves a folder for the section "news" with the tone "Brisk."
    Then the section "news" has its own writing guidelines at version 1
    And the publication's writing guidelines are still at version 1
