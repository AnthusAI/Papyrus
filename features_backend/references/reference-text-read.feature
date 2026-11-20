@backend @reference-text
Feature: An agent reads the text the newsroom captured for a Reference
  `papyrus references text --reference ID|LINEAGE [--offset N] [--limit N] [--json]` prints a slice of the stored capture, so an agent reads it instead of
  fetching the page again. The slice comes with the total length, the offset, the source, when it was captured, and whether the capture itself was cut at the
  reader's size guard (`truncated`). The command only reads. A Reference with no captured text says so and exits non-zero. Nothing here reaches a real site.

  Scenario: A slice of a long capture says how much is left
    Given a Reference whose captured text is 50 characters long and was cut at the size guard
    When an agent reads its text from offset 10 with a limit of 20
    Then it receives 20 characters, the total 50, truncated yes, and the next offset 30

  Scenario: Reading to the end
    Given a Reference whose captured text is 50 characters long and was cut at the size guard
    When an agent reads its text from offset 40 with no limit
    Then it receives 10 characters and no next offset

  Scenario: A Reference with nothing captured
    Given a Reference with no captured text
    When an agent reads its text from offset 0 with a limit of 20
    Then the read reports that nothing was captured
