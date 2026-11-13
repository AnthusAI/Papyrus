@backend @multilingual
Feature: The publication's voice applies in every language; a language overlay adds what is particular to it
  Voice, audience, structure and binding rules are written once, in the publication's guidelines and its sections', and they apply to every
  language. A language overlay (writing guidelines saved with a language, for the publication or for one section) holds only what is particular
  to that language: register notes, words to prefer and avoid, the target locale's conventions for naming organisations and people, glossary
  entries. Resolving the guidelines for a Story in a language lays its overlays over the shared layers and says which layer each part came from.
  Saving an overlay draws checks written for that language only. The locale's conventions are expressed here and in the glossary, never by
  leaving out or changing a fact; the translation procedure that applies them and re-checks every claim against the English is PPY-843a7c.
  (PPY-d0132d; an in-memory backend that fails on any table scan; no model is called.)

  Background:
    Given the publication's writing guidelines set the audience "General readers", the tone "Warm." and the binding rule "no-hype"
    And the section "security" writing guidelines add the tone "Precise about threats."
    And a Chinese overlay adds the tone "称呼读者用“您”，语气正式。" and avoids the word "赋能"

  Scenario: The publication's voice applies in every language
    When the guidelines are resolved for a Chinese Story in the "security" section
    Then the resolved tone is "Warm. | Precise about threats. | 称呼读者用“您”，语气正式。"
    And the resolved audience is "General readers" and the binding rule "no-hype" is there
    And the tone came from the layers "publication, section, language zh-Hans"
    And the audience and the binding rule came from the publication alone
    And the layers used are "publication, section, language zh-Hans"

  Scenario: An English Story never reads the Chinese overlay
    When the guidelines are resolved for an English Story in the "security" section
    Then the resolved tone is "Warm. | Precise about threats."
    And the layers used are "publication, section"

  Scenario: The target locale's conventions come from the overlay
    Given the Chinese overlay records the approved Chinese form "苏黎世联邦理工学院" of the organisation "ETH Zurich"
    When the guidelines are resolved for a Chinese Story in the "security" section
    Then the resolved glossary gives "苏黎世联邦理工学院" for "ETH Zurich"
    When the guidelines are resolved for an English Story in the "security" section
    Then the resolved glossary has no entry for "ETH Zurich"

  Scenario: A language overlay cannot set binding rules
    Given the Chinese overlay also tries to set the binding rule "no-numbers"
    When the guidelines are resolved for a Chinese Story in the "security" section
    Then the binding rules are only "no-hype"
    And the warning "language_constraint_ignored" is given

  Scenario: Saving the Chinese overlay draws Chinese checks only
    Then a publication check "avoid-lexicon" written for "zh-Hans" detects "赋能" with the source "writing-guidelines:editorial-doctrine-writing-lang-zh-hans:v1"
    And the English check "avoid-lexicon" still detects only "synergy"
    And checking Chinese text "赋能是关键。" finds "赋能" and checking English text "Pure synergy." does not run the Chinese check

  Scenario: A Chinese overlay saved as zh-CN is the zh-Hans overlay
    When an admin reads the writing guidelines overlay for "zh-CN"
    Then it is the overlay stored under the slug "editorial-doctrine-writing-lang-zh-hans"

  Scenario: An overlay for a language Humanus cannot read is refused
    When an admin saves a writing guidelines overlay for "ko"
    Then the save is refused as invalid input naming "ko"
