Feature: A translated Story may show a localized picture, and never needs to
  A translation is its own Story (`<story>--<language>`), so the pictures it shows are the ones its own body and front matter name. By default
  those are the original's pictures, with the alt text and caption translated. That is complete: no translation waits for, asks for or is blocked
  by a localized picture. When a picture holds words (a figure with labels), a person may choose to give the translation its own version of it:
  a stored light and dark picture that the translation's figure and cover point at instead, recorded in the translation's front matter as
  `imageVariants` (the original it stands in for, the variant, the language). Pages, cards, social previews, Markdown copies and feeds already read
  the translation's own body and front matter, so they show the variant with no change of their own. The translation procedure only says, as advice,
  which pictures hold words and have no variant yet; it never changes a picture itself and a re-translation keeps every variant.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"

  Scenario: Without a variant the translation shows the original picture with its alt text translated
    Given the English Story has the stored picture "assets/waymo.png"
    When the translation run for "es-419" runs
    Then the run is saved, not held
    And the translation's figure shows "assets/waymo.png" with the alt text "Un auto sin conductor"
    And the translation records no picture variant
    And the run reports 0 pictures that hold words

  Scenario: A figure that holds words is reported as advice, and the run is not held
    Given the English Story has the stored picture "assets/waymo.png" that its figure record says holds 3 labels
    When the translation run for "es-419" runs
    Then the run is saved, not held
    And the run reports 1 picture that holds words
    And the translation's record names "assets/waymo.png" as holding words and not localized

  Scenario: A localized figure is saved into the translation and the original Story is untouched
    Given the translation run for "es-419" has finished
    When an editor saves the pictures "assets/es/waymo-es.png" and "assets/es/waymo-es.dark.png" as the "es-419" variant of "assets/waymo.png"
    Then the translation's figure shows "assets/es/waymo-es.png" with the dark picture "assets/es/waymo-es.dark.png"
    And the translation records "assets/es/waymo-es.png" as the "es-419" variant of "assets/waymo.png"
    And the English Story's version is unchanged

  Scenario: A localized figure survives a re-translation of a changed source
    Given the translation run for "es-419" has finished
    And an editor saves the pictures "assets/es/waymo-es.png" and "assets/es/waymo-es.dark.png" as the "es-419" variant of "assets/waymo.png"
    When the English Story is republished as version 4 with one paragraph changed and the translation asked for again
    And the translation run for "es-419" runs
    Then the run is saved, not held
    And the translation's figure shows "assets/es/waymo-es.png" with the dark picture "assets/es/waymo-es.dark.png"
    And the run reports 0 pictures that hold words
