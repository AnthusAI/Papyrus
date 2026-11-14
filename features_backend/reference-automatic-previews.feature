@backend @reference-previews
Feature: A new Reference gets its link preview when it is created
  The References feed shows a picture, a one-line dek and the site name on every card, all taken from the source page's own link-preview
  metadata. Papyrus used to write them only when someone ran the backfill command. Now the monitoring router writes the preview as soon as
  it delivers a new pending Reference, so the card is complete the first time an editor sees it. The page was already read when the item
  was curated, so the router reuses that reading and does not fetch the page a second time. The preview is decoration: whatever goes wrong
  with it, the Reference is still delivered, and a Reference that already existed is left alone. The backfill command stays for older
  References and for refreshing.

  Scenario: A new Reference gets the preview image its page declares
    Given a collected item whose page declares the picture "https://cdn.example.org/alpha.jpg" and the dek "Regulators approved a scheme."
    When the router delivers the item as a new Reference
    Then the Reference has a preview attachment whose image is "https://cdn.example.org/alpha.jpg"
    And the preview holds the dek "Regulators approved a scheme."
    And the page was not fetched again for the preview

  Scenario: A page that declares no picture is recorded as checked
    Given a collected item whose page declares no picture and no dek
    When the router delivers the item as a new Reference
    Then the Reference has a preview attachment with no image that records when it was checked
    And the page was not fetched again for the preview

  Scenario: A preview that cannot be fetched never stops the Reference from being delivered
    Given a collected item whose curation did not keep the page's preview
    And the page cannot be fetched when the preview is attempted
    When the router delivers the item as a new Reference
    Then the Reference is delivered
    And the Reference has no preview attachment
    And the failure was logged as a preview failure

  Scenario: A Reference that already existed is not fetched again
    Given a collected item whose page declares the picture "https://cdn.example.org/alpha.jpg" and the dek "Regulators approved a scheme."
    When the router delivers the item and finds the Reference already existed
    Then the Reference is delivered
    And no preview was attempted
