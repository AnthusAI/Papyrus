Feature: Review one submitted email without listing other submissions
  Editors can open a known receipt directly and use the normal candidate controls.
  Opening a receipt never loads or refreshes the monitoring summary list.

  Scenario: Single-receipt access stays limited during loading and failures
    Given a synthetic email receipt API that refuses overview reads
    When the editor opens known, empty, denied, unavailable, and superseded receipts
    Then each email request stays confined to the selected receipt
    And no monitoring overview or refresh timer is started
