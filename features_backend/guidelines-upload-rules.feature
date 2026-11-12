Feature: Guideline documents pass the same upload rules as every other attachment
  A guideline document, the design system a site draws with and the visual style profile are each saved as one JSON file attached to a version of a
  private record, and the files a design system names (its fonts) are attached beside it. The attachment upload function on a deployed backend decides
  which kinds of attachment it accepts, by the role the file plays and the media type it carries. Those kinds were once missing the guideline roles, so
  a deployed backend refused every guideline save with "Unsupported ModelAttachment role", while the in-memory fakes that stand in for S3 in the specs
  accepted anything and so hid it. The fakes now apply the upload function's own rules, read from its source, so a role the function does not accept
  fails here before it can fail on a site.

  Scenario: A guidelines document is saved and read back through the upload function's rules
    Given a publication with no guidelines
    When an admin saves a writing document whose body says "Write plainly." with the reason "First guidelines"
    Then the saved file is a "doctrine_document" of JSON, which the upload function's rules accept
    And reading the writing guidelines returns the same document, and the row's content hash matches it

  Scenario: The files a document names are accepted as raw bytes
    Given an S3 side that applies the upload function's rules
    When a "doctrine_asset" file of type "application/octet-stream" is offered to the upload function
    Then the upload function would accept it

  Scenario: A guideline document does not take pictures and an asset does not take JSON
    Given an S3 side that applies the upload function's rules
    When a "doctrine_document" file of type "image/png" is offered to the upload function
    Then the upload function would refuse it because of the media type
    When a "doctrine_asset" file of type "application/json" is offered to the upload function
    Then the upload function would refuse it because of the media type

  Scenario: A role the upload function does not know is refused in its own words
    Given an S3 side that applies the upload function's rules
    When a "made_up_role" file of type "application/json" is offered to the upload function
    Then the upload function would refuse it with "Unsupported ModelAttachment role made_up_role"
