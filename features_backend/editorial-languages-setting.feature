Feature: Which languages are public, and how each is served, are set in one place with one set of rules
  A site that writes in more than one language says how it serves them in the one languages setting: which enabled languages are public, the URL prefix of
  each language and each language's slug policy. An enabled language that is not public is written, translated and checked but gets no page. The console form
  (Administration, Editorial checks) and the command `papyrus editorial languages` both read and change those keys, and both are checked by the same
  rules the projection applies, before anything is saved. A change touches only the keys it names; every other stored setting stays as it is.

  Background:
    Given a site whose stored settings write in "en, es-419, zh-Hans" with "en" as the primary and the house guidance "Plain words."

  Scenario: Listing shows each language's public state, prefix and slug policy, and marks the defaults
    When the editor runs the languages command "papyrus editorial languages"
    Then the listing says "es-419" is not public, served under "/es/ (default)" with the slug policy "translated (default)"
    And the listing says "zh-Hans" is served under "/zh/ (default)" with the slug policy "characters (default)"
    And no setting is written

  Scenario: Making a language public adds the primary, since it is always public, and keeps every other stored setting
    When the editor runs the languages command "papyrus editorial languages --set-public es-419"
    Then the stored public languages are "en, es-419"
    And the stored house guidance is still "Plain words."
    And the stored languages still hold the key "futureKey" untouched
    And the listing says "es-419" is public

  Scenario: A dry run shows the result and writes nothing
    When the editor runs the languages command "papyrus editorial languages --set-public es-419 --dry-run"
    Then the listing says "es-419" is public
    And no setting is written

  Scenario: A prefix and a slug policy are set for one language and leave the others alone
    When the editor runs the languages command "papyrus editorial languages --set-prefix es-419=es-latam --set-slug es-419=primary"
    Then the stored prefix of "es-419" is "es-latam" and its slug policy is "primary"
    And "zh-Hans" has no stored prefix and no stored slug policy

  Scenario: An empty value returns a language to its default
    Given the stored prefix of "es-419" is "latam"
    When the editor runs the languages command "papyrus editorial languages --set-prefix es-419="
    Then "es-419" has no stored prefix
    And the listing says "es-419" is served under "/es/ (default)" with the slug policy "translated (default)"

  Scenario: Making only the primary public removes the public list, which means the same
    Given the stored public languages are "en, es-419"
    When the editor runs the languages command "papyrus editorial languages --set-public ''"
    Then the stored languages hold no public list

  Scenario Outline: A change the projection would refuse is refused before it is saved
    When the editor runs the languages command "<command>"
    Then the languages command is refused saying "<message>"
    And no setting is written

    Examples:
      | command                                                   | message                                          |
      | papyrus editorial languages --set-prefix es-419=zh        | zh-Hans and es-419 would both be served under /zh/ |
      | papyrus editorial languages --set-public es               | languages.public names es, which the site does not write in |
      | papyrus editorial languages --set-slug es-419=shortest    | is not one of translated, characters, pinyin, primary |
      | papyrus editorial languages --set-slug en=primary         | languages.slugs names en, which is not an enabled language other than the primary |
      | papyrus editorial languages --set-prefix es-419=Es_Latam  | is not a lowercase path segment                  |

  Scenario: The console asks the same question and gets the same words and the defaults
    When the console form describes the languages with "es-419" and "es" both enabled
    Then the console form is told "would both be served under /es/"
    When the console form describes the stored languages
    Then the console form is told the default prefix of "es-419" is "es" and its default slug policy is "translated"
    And the console form is told the default slug policy of "zh-Hans" is "characters"

  Scenario: Translating on publish is off until it is turned on, and turning it on needs an automation
    When the editor runs the languages command "papyrus editorial languages"
    Then the listing says translating on publish is off
    When the editor runs the languages command "papyrus editorial languages --auto on"
    Then the command is refused saying to name the Automation that runs the translation procedure
    And no setting is written

  Scenario: Turning translate on publish on and off keeps the automation and the publish choice
    When the editor runs the languages command "papyrus editorial languages --auto on --auto-automation mom.story-localize"
    Then the stored auto setting is on, with the automation "mom.story-localize", publishing clean translations
    And the listing says translating on publish is on with the automation "mom.story-localize"
    When the editor runs the languages command "papyrus editorial languages --auto-publish off"
    Then the stored auto setting is on, with the automation "mom.story-localize", saving translations for a person to publish
    When the editor runs the languages command "papyrus editorial languages --auto off"
    Then the stored auto setting is off, with the automation "mom.story-localize" kept

  Scenario: Translating on publish needs a language to translate into
    Given a site whose stored settings write in "en" with "en" as the primary and the house guidance "Plain words."
    When the editor runs the languages command "papyrus editorial languages --auto on --auto-automation mom.story-localize"
    Then the command is refused saying the site has no language to translate into

  Scenario: An unknown key under auto is refused naming it
    Given the stored auto setting has the key "everything"
    When the editor runs the languages command "papyrus editorial languages"
    Then the command is refused naming the key "everything"

