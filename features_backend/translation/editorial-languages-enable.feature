Feature: A language is enabled and disabled with the languages command
  A site starts writing in a language, or stops, with `papyrus editorial languages --enable TAG` and `--disable TAG`, the same setting the console form
  changes under "Languages the site writes in". An enabled language is written, translated and checked; it is never public until `--set-public` says so.
  Enabling imports the language's starter policy packs and says what else the language needs (its writing and glossary overlays, a register choice) as
  commands to run next: those overlays are choices of the site and are not invented. Both commands work in a dry run, change nothing that is already as
  asked, and refuse what the console form refuses. Disabling is refused for the primary language and for a language that has translations.

  Background:
    Given a site whose stored settings write in "en" with "en" as the primary and the house guidance "Plain words."

  Scenario: Enabling a language adds it, keeps it out of the public site and imports its starter packs
    When the editor runs the languages command "papyrus editorial languages --enable es-419"
    Then the stored enabled languages are "en, es-419"
    And the stored languages hold no public list
    And the stored house guidance is still "Plain words."
    And the stored languages still hold the key "futureKey" untouched
    And the site has the starter packs "ai-writing-tells, typography-es, ai-writing-tells-es, initialisms-es, word-choice-es-419"
    And the listing says "es-419" is not public, served under "/es/ (default)" with the slug policy "translated (default)"

  Scenario: The command says exactly what it did and what to run next
    When the editor runs the languages command "papyrus editorial languages --enable es-419"
    Then the command output says "Did enable es-419: written, translated and checked, not public"
    And the command output says "Did import the starter pack word-choice-es-419"
    And the command output says "Saved."
    And the command output says "papyrus guidelines save --kind writing --language es-419 --file OVERLAY.json"
    And the command output says "register (usted or tu)"
    And the command output says "papyrus guidelines save --kind glossary --language es-419"
    And the command output says "papyrus stories localize --story LINEAGE --language es-419 --dry-run"
    And the command output says "papyrus editorial languages --set-public es-419"

  Scenario: A dry run says what would happen and writes nothing
    When the editor runs the languages command "papyrus editorial languages --enable es-419 --dry-run"
    Then the command output says "Would enable es-419"
    And the command output says "Would import the starter pack typography-es"
    And the command output says "Dry run: nothing was written."
    And no setting is written
    And the site has no starter packs

  Scenario: Running it again changes nothing
    Given the editor has run the languages command "papyrus editorial languages --enable es-419"
    When the editor runs the languages command "papyrus editorial languages --enable es-419"
    Then the command output says "Nothing to change"
    And no setting is written

  Scenario: Several languages are enabled together, each in Humanus's spelling
    When the editor runs the languages command "papyrus editorial languages --enable es-419,zh-CN"
    Then the stored enabled languages are "en, es-419, zh-Hans"
    And the site has the starter packs "typography-zh-hans, translationese-zh-hans, ai-writing-tells-zh-hans, word-choice-es-419"

  Scenario: An enabled language whose starter packs were never imported gets them
    Given the stored languages write in "en, es-419" with "en" as the primary
    When the editor runs the languages command "papyrus editorial languages --enable es-419"
    Then the stored enabled languages are "en, es-419"
    And the site has the starter packs "word-choice-es-419"
    And the command output says "Did import the starter pack word-choice-es-419"

  Scenario: Enabling the language together with serving settings writes them in one save
    When the editor runs the languages command "papyrus editorial languages --enable es-419 --set-prefix es-419=latam --set-slug es-419=primary"
    Then the stored enabled languages are "en, es-419"
    And the stored prefix of "es-419" is "latam" and its slug policy is "primary"

  Scenario: The result is shown as JSON with the packs and the next commands
    When the editor runs the languages command "papyrus editorial languages --enable es-419 --json"
    Then the JSON output lists "es-419" as enabled and as not public
    And the JSON output lists the starter pack "word-choice-es-419" as not applied before
    And the JSON output has next commands naming "es-419"

  Scenario Outline: A request that cannot be honoured is refused before anything is saved
    Given the stored languages write in "en, es-419" with "en" as the primary and "es-419" has <count> translated Stories
    When the editor runs the languages command "<command>"
    Then the languages command is refused saying "<message>"
    And no setting is written

    Examples:
      | count | command                                             | message                                                   |
      | 0     | papyrus editorial languages --enable ko             | Humanus has no language pack for 'ko'                     |
      | 0     | papyrus editorial languages --enable es             | es and es-419 would both be served under /es/|
      | 0     | papyrus editorial languages --enable ''             | --enable takes language tags                              |
      | 0     | papyrus editorial languages --enable '*'            | * is only a policy's language                             |
      | 0     | papyrus editorial languages --disable en            | primary language                                          |
      | 0     | papyrus editorial languages --enable zh-Hans --disable zh-Hans | cannot be enabled and disabled in one command  |
      | 3     | papyrus editorial languages --disable es-419        | es-419 has 3 translated Stories                           |
      | 1     | papyrus editorial languages --disable es-419        | es-419 has 1 translated Story                             |

  Scenario: A language with no translations is disabled and takes its serving settings with it
    Given the stored languages write in "en, es-419" with "en" as the primary and "es-419" has 0 translated Stories
    And the stored prefix of "es-419" is "latam"
    And the stored public languages are "en, es-419"
    When the editor runs the languages command "papyrus editorial languages --disable es-419"
    Then the stored enabled languages are "en"
    And the stored languages hold no public list
    And "es-419" has no stored prefix
    And the command output says "Did disable es-419"

  Scenario: Disabling a language the site does not write in changes nothing
    When the editor runs the languages command "papyrus editorial languages --disable zh-Hans"
    Then the command output says "Nothing to change"
    And no setting is written

  Scenario: Disabling does not look for translations of a language the site never wrote in
    When the editor runs the languages command "papyrus editorial languages --disable zh-Hans --dry-run"
    Then no translation count was asked for
