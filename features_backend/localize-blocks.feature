Feature: A directive stays one block of a translation however its attributes are written
  A translation is made block by block. A leaf directive such as ::image{ ... } whose attribute list runs over several lines, even with a blank line inside it, is
  one block that the system holds and the translator never sees as prose: a credit stays as written and the closing brace is never lost. A body cut at that
  blank line left its second half to the translator, which translated the credit and dropped the brace, and the translation was held for a citation check that
  could no longer read the rest of the page.

  Scenario: A picture directive with a blank line inside its attributes is one block
    Given a body with a picture directive whose attributes have a blank line inside
    When the body is cut into blocks
    Then the picture directive is one block, whole, between the two paragraphs
