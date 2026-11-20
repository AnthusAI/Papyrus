Feature: Saving a Story derives its body from the Markus source
  Every way of saving a Story derives the stored body from the Markus source the author wrote, so the two can never disagree. When
  the source has a problem, such as an unknown directive, an unknown citation key or an unsafe image address, the author gets an
  error code that says what to fix.

  Scenario: A valid article derives an IR envelope
    When I derive the body of an article with a paragraph and a citation
    Then the derivation is ok
    And the envelope has schema version 1 and one paragraph block
    And the bibliography has 1 entry

  Scenario: An unknown directive is reported with a code
    When I derive the body of an article using the directive "nope"
    Then the derivation fails with code "markus-validation"
    And no body IR is produced

  Scenario: An unknown citation key is reported
    When I derive the body of an article citing a missing key
    Then the derivation fails with code "citation-key"
    And no body IR is produced

  Scenario: An unsafe image source is reported
    When I derive the body of an article with the image source "javascript:alert(1)"
    Then the derivation fails with code "image-src"
    And no body IR is produced
