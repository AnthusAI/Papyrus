@backend @multilingual
Feature: The bilingual judge reads the notes the translator was given
  A satire site's pun or idiom, rendered with an equivalent in Spanish, is not word for word the source. The translation procedure gave the translator the
  language overlay's notes (register, tone, words to prefer and avoid) but not the judge, so a legitimate creative rendering was judged a mistranslation and
  held. The faithfulness check now passes the same notes to Humanus's bilingual judge, which treats a rendering the notes permit as no problem unless it
  changes the claim, who says it, or who or what is mocked. Without notes the judge reads the block as before. Names, quotations, numbers, hedges and links
  stay parity checks and do not depend on the notes. (Humanus `translationNotes`; the judge is scripted here and nothing reaches a model.)

  Background:
    Given the publication's writing guidelines set the audience "General readers", the tone "Warm." and the binding rule "no-hype"

  Scenario: An idiom rendered with an equivalent idiom passes when the overlay permits equivalents
    Given a Spanish overlay for "es-419" sets the tone "Satire. Render wordplay and idioms with an equivalent in Spanish."
    And a model judge that reports the idiom unless the prompt carries notes that permit an equivalent
    When the guidelines are resolved for a Spanish Story in the "security" section
    And the faithfulness check reads "The board let the budget go to the dogs." and its translation "La junta dejó que el presupuesto se fuera al traste." with the language's notes
    Then the judge reports nothing and its prompt lists the overlay tone "Satire. Render wordplay and idioms with an equivalent in Spanish."
    And the checker's versions name the notes only when there are some

  Scenario: The same translation without an overlay that permits it is still held
    Given a model judge that reports the idiom unless the prompt carries notes that permit an equivalent
    When the faithfulness check reads "The board let the budget go to the dogs." and its translation "La junta dejó que el presupuesto se fuera al traste." with the language's notes
    Then the translation is held for the judge's report on "go to the dogs"
    And the judge's prompt has no notes
    And the checker's versions name the notes only when there are some

  Scenario: A rendering that changes who is mocked is held even when the overlay permits equivalents
    Given a Spanish overlay for "es-419" sets the tone "Satire. Render wordplay and idioms with an equivalent in Spanish."
    And a model judge that reports who is mocked as changed whatever the notes say
    When the guidelines are resolved for a Spanish Story in the "security" section
    And the faithfulness check reads "The regulators let the chatbot write its own safety report." and its translation "El chatbot dejó que los reguladores redactaran su propio informe de seguridad." with the language's notes
    Then the translation is held for the judge's report on "The regulators let the chatbot"
    And the judge prompt lists the overlay tone "Satire. Render wordplay and idioms with an equivalent in Spanish."
