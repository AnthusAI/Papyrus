Feature: References are read by the date the source published them, through an index
  An editor or an editor's agent often asks about "the last two weeks" of References. A Reference can reach the newsroom days or weeks after its
  source published it, so the question is about the source date (Reference.sourcePublishedAt), never the date it was captured. The References table is
  large and must never be read whole to answer such a question. Reference therefore has one index by corpus and source date,
  listReferencesByCorpusAndSourcePublishedAt, which hands back only the rows whose source date lies between two values, newest first, a page at a time.
  The index uses attributes the table already has, so it needs no new field and no backfill. It is one new index on the Reference table, so it ships
  in a data API release of its own, and a site without it answers service_unavailable rather than falling back to a scan. The index can only say
  corpus and date; the vote, the section a vote was filed under, the monitor and the version are kept or dropped on each returned page. A Reference
  with no source date, or one whose source date is not written as an ISO date, is not in the index and is not seen. Nothing here calls AWS or a model.

  Scenario: The index exists in both schema files and in the client
    Then the Reference model in the deployed schema and in the typed schema both declare the index on corpusId and sourcePublishedAt
    And the authoring client knows the index and reads it by a range of source dates, newest first, a page at a time

  Scenario: A window asks the index for its days and nothing else
    Given a corpus with References published on many days, some already voted down or archived and some replaced by a newer version
    When the References of the last 14 days ending on 2026-11-08 are selected
    Then the index is asked once for the corpus between 2026-10-26 and the end of 2026-11-08
    And only the current accepted and pending References of those days are returned

  Scenario: The section, the monitor and the vote narrow the returned rows
    Given a corpus with References from two sections and two monitors
    When the References of the window are selected for one section
    Then only the References whose vote was filed under that section are returned
    When the References of the window are selected for one monitor
    Then only the References that monitor delivered are returned
    When rejected References are asked for
    Then only the rejected References of the window are returned

  Scenario: A safety stop is never quiet
    Given a corpus with ten References in the window
    When the References of the window are selected with a safety stop of four
    Then four References are returned and the selection is marked stopped
    And the warnings say the safety stop was reached and name the limit
    And the log says the same

  Scenario: Selecting a window is not a whole-table read
    Then the topics code makes no whole-table read and the allowlist of whole-table reads has no new entry
