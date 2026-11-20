@backend @reference-public-fields
Feature: A Reference carries what a public card needs, so a block can ask an index for the rows it shows
  A public block (the three newest accepted References, the six most confident recommended ones) should not read the whole table to find a few
  cards. The design (docs/plans/public-blocks-from-indexes.md) gives each Reference row six plain attributes and, in a later and separate
  deploy, one index over two of them. This feature covers the attributes and the code that keeps them right; nothing here adds the index.
  "publicFeedKey" and "publicOrderKey" say where the row sits: an accepted Reference is in its corpus's accepted partition, sorted by the
  Cyclotron's original chance that an editor accepts it (a Reference nobody scored sorts after every scored one); a pending Reference is in
  the recommended partition of the day it arrived only when it has a stored prediction of one half or more. A pending Reference with no
  prediction is never treated as one half, so it is in no partition and no page can show it. "cardImage", "cardSummary", "cardSiteName" and "cardPageTitle" (the title the page declared, for a Reference titled with its own address)
  are copied from the Reference's preview when the preview is captured, and a video's picture is its own thumbnail copy, never an address on
  the platform. Every writer that changes a vote, a prediction or a version keeps the keys right, and the one backfill that reads existing
  rows previews by default and writes nothing a second time. Nothing here touches production: the backend is in memory.

  Scenario: An accepted Reference is public, and one nobody scored sorts after every scored one
    Given two accepted References that arrived at "2026-11-02T12:00:00Z", one scored 0.2 and one nobody scored
    Then the scored one is in the accepted public partition sorted by "p0.200000"
    And the unscored one is in the accepted public partition sorted by "n"
    And the scored one sorts above the unscored one

  Scenario: A pending Reference predicted at one half or more is recommended on the day it arrived
    Given a Reference that is "pending", arrived at "2026-11-02T23:30:00-05:00" and has a stored prediction of 0.5
    Then it is in the recommended public partition of "2026-11-03"

  Scenario: A pending Reference nobody predicted is never treated as one half
    Given a Reference that is "pending", arrived at "2026-11-02T12:00:00Z" and has no prediction
    Then it is in no public partition
    And writing it names no public attribute at all

  Scenario: A pending Reference predicted below one half is in no public partition
    Given a Reference that is "pending", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.499999
    Then it is in no public partition

  Scenario: A vote moves a recommended Reference into the accepted partition and keeps its place in the order
    Given a Reference that is "pending", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.7
    When an editor accepts it
    Then it is in the accepted public partition sorted by "p0.700000"

  Scenario: A rejection or an archive takes a public Reference out of the index
    Given a Reference that is "pending", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.7
    When an editor rejects it
    Then it is in no public partition
    And clearing it names both public attributes

  Scenario: The Cyclotron recording its first prediction brings a pending Reference in
    Given a Reference that is "pending", arrived at "2026-11-02T12:00:00Z" and has no prediction
    When the Cyclotron decides "include" with 90% confidence
    Then it is in the recommended public partition of "2026-11-02"

  Scenario: Capturing a preview copies the picture, the description and the site name onto the row
    Given a Reference that is "accepted", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.8
    When its page preview is captured with a picture, a long description and a site name
    Then the row holds the picture address, the whole description and the site name
    And capturing the same preview again writes nothing more to the row

  Scenario: Nothing private is copied onto a card
    Given a Reference that is "accepted", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.8
    When its page preview is captured with an email address and an identifier in the description
    Then no card attribute holds an email address or an identifier

  Scenario: A video's card shows our own copy of its thumbnail
    Given a video Reference that is "accepted", arrived at "2026-11-02T12:00:00Z" and has a stored prediction of 0.8
    When its page preview is captured with the platform's own picture
    Then the row's card picture is empty
    When its thumbnail copy is recorded
    Then the row's card picture is the thumbnail copy

  Scenario: The backfill previews by default and reads only the rows a page can show
    Given a corpus with 3 accepted References and pending ones predicted 0.9, 0.7, none, 0.3, 0.2 and 0.1
    When the public-fields backfill runs as a preview
    Then it writes nothing
    And it reports 5 public rows
    And it read the pending index down to the first row under one half and no further

  Scenario: The backfill writes once and a second run writes nothing
    Given a corpus with 3 accepted References and pending ones predicted 0.9, 0.7, none, 0.3, 0.2 and 0.1
    When the public-fields backfill runs with writing on
    Then it wrote 5 rows
    And no vote was changed
    When the public-fields backfill runs with writing on
    Then it wrote nothing more
