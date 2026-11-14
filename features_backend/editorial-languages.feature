@backend @editorial-checks @multilingual
Feature: Each language of a publication is checked against its own rules
  A Chinese or Spanish Story must never be judged by English phrase rules, and English text never by Chinese ones. Every editorial policy
  says which language it is written for (or "*" for a rule that holds in every language), every check names the language of its text,
  and Humanus reads the text in that language or refuses it: a language it has no pack for is never read as English. A site's editorial
  settings name the languages it writes in, each as the exact variant (Machines on Machines writes neutral Latin American Spanish, es-419),
  and enabling a language brings that language's starter rules. The publication's voice and binding rules are written once; a language
  overlay of the writing guidelines adds only what is particular to the language. (PPY-d0132d; the data is synthetic and no model is called.)

  Background:
    Given a site that writes in "en, zh-Hans, es-419" with English as its primary language
    And the site's starter rules for every language it writes in

  Scenario: An English Story is checked in English with the same findings as before the language layer
    Given the site's English policies of the regression story, with the rules lane only
    When the English regression story is checked as a saved Story
    Then Humanus was asked to read it as "en"
    And the findings are exactly those recorded with Humanus 0.34 before Stories had a language

  Scenario: A Chinese Story is not checked against English phrase rules
    When a Chinese localization saying "值得注意的是,这个工具至关重要。It's worth noting." is checked
    Then only Chinese and language-neutral policies ran
    And the findings are for policies "stock-connectives, punctuation-width, inflated-vocabulary"
    And the check result names the language pack "zh-Hans" and its version

  Scenario: A stored check is not reused once Humanus reads the language differently
    When the English pack is composed under the installed Humanus English language pack
    And the English pack is composed again after Humanus's English language pack changes version
    Then the two pack versions differ

  Scenario: A language-neutral policy runs in every language
    Given a language-neutral policy "no-placeholders" that flags "[INSERT"
    When a Chinese localization saying "这是[INSERT 名字]的工具。" is checked
    And English text saying "Meet [INSERT name] today." is checked
    Then both checks have a "no-placeholders" finding

  Scenario: The site's Spanish variant is a setting
    When Spanish text saying "Reinició el ordenador por un fallo." is checked as "es"
    Then Humanus was asked to read it as "es-419"
    And the findings are, by policy, excerpt and replacement:
      | policy      | excerpt   | replacement |
      | computadora | ordenador | computadora |
      | falla       | fallo     | falla       |

  Scenario: A variant's own policy replaces its base language's policy with the same key
    Given a Spanish policy "registro" that flags "ordenador"
    And a Latin American Spanish policy "registro" that flags "fallo"
    When Spanish text saying "Reinició el ordenador por un fallo." is checked as "es-419"
    Then the "registro" finding's excerpt is "fallo"

  Scenario: A section's policy for a language replaces the publication's in that language only
    Given a Chinese policy "house-words" that flags "赋能"
    And the section "security" has a Chinese policy "house-words" that flags "抓手"
    When a Chinese localization saying "赋能是一个抓手。" is checked in the section "security"
    Then the "house-words" finding's excerpt is "抓手"
    When a Chinese localization saying "赋能是一个抓手。" is checked in the section "culture"
    Then the "house-words" finding's excerpt is "赋能"

  Scenario: A language Humanus has no pack for is refused, naming it
    When text is checked as "ko"
    Then the check is refused and the message names "ko"
    And Humanus was not asked to check

  Scenario: A language the site does not write in is refused, naming it
    Given the site's settings enable "en, zh-Hans"
    When text is checked as "es"
    Then the check is refused because the site does not write in "es"

  Scenario: A regional variant Humanus does not have is refused, never read as another
    When text is checked as "es-ES"
    Then the check is refused and the message names "es-ES"
    And Humanus was not asked to check

  Scenario: A site cannot enable a language Humanus cannot read
    Given the site's settings enable "en, ko"
    When English text saying "Hello." is checked
    Then the check is refused and the message names "ko"

  Scenario: A check always names its language
    When text is checked without a language
    Then the check is refused because the language was not given
    And Humanus was not asked to check

  Scenario: Turning on a language brings its starter rules
    Then the site has policies from these starter packs, each written for its pack's language:
      | pack                     | language |
      | ai-writing-tells         | en       |
      | typography-zh-hans       | zh-Hans  |
      | translationese-zh-hans   | zh-Hans  |
      | ai-writing-tells-zh-hans | zh-Hans  |
      | typography-es            | es       |
      | ai-writing-tells-es      | es       |
      | word-choice-es-419       | es-419   |
    And the starter pack catalog marks those packs as defaults and "plain-language" as not

  Scenario: Policies saved before policies had a language get theirs written once
    Given an older policy "no-hype" from the panel with no language
    And an older policy "chatbot-artifacts" from the starter pack "ai-writing-tells" with no language
    When the deploy ensures the default policies
    Then the policy "no-hype" is written for "en" and keeps its id and version
    And the starter policy "chatbot-artifacts" is written for "en"
    And running it again writes no language

  Scenario: A policy with no language is refused, never guessed
    Given an older policy "no-hype" from the panel with no language
    When English text saying "A game-changing release." is checked
    Then the check is refused and the message names "no-hype"

  Scenario: The command line checks a draft in the language it is given
    When an operator checks a "zh-Hans" draft saying "值得注意的是,真的。" with papyrus editorial check
    Then the printed result names the language pack "zh-Hans"
    And the printed result has a "stock-connectives" finding
