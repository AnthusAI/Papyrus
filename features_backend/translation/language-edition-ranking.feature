Feature: A language edition ranks its Stories as their originals are ranked
  The home and the listings of a language edition list its Stories in the order of the Story ranking (the newest rolling bucket first, the editors' private
  stars inside it). A translation is not rated and is not published on the day its original was: it stands where its original stands. It takes the original's
  publication date, which fixes its bucket and the date its card shows unless it has a date of its own, and the original's stars, so the Spanish
  home lists the translated Stories in the order the English home lists them, and the lead of an edition is the highest-ranked Story that has been
  translated. A rating of the original moves the translation with it, and the stars are read here and printed nowhere.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings

  Scenario: The Spanish listings follow the English order, whatever order the translations were published in
    Given the English articles "alpha-star", "mid-plain" and "new-plain" are published on the 9th, the 11th and the 12th
    And the editors rated "alpha-star" 5 stars
    When their Spanish translations are published on the 15th without a date of their own, "new-plain" first and "alpha-star" last
    Then the English articles listing and home list "alpha-star", "new-plain", "mid-plain" in that order
    And the Spanish articles listing and home list their translations in that same order
    And the Spanish card of "alpha-star" shows the date of its original, the 9th
