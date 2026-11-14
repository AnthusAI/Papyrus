Feature: A story has exactly one row in the stage head index
  A story is stored as one Item row per saved version, and each version keeps the stage it was written in. The old stage index
  (`stage` + `updatedAt`) therefore holds every version: a story published twelve times has twelve rows in Published, and a story
  that went through Copywriting still has a row there after it is published. A board column that reads 25 rows can then show an old
  version, and every list built on that index reads every version only to drop most of them.

  The head stage index fixes that with one sparse attribute. `headStageKey` is carried by the head row of a lineage only, the row that
  is not superseded, and equals that row's stage (`<tenant>#<stage>` on a backend that serves several tenants). DynamoDB leaves a row
  without the attribute out of the index `listItemsByHeadStageAndUpdatedAt`, so the index holds one row per story. Version rows stay as
  history, untouched, with their own stage.

  Every writer that sets a stage or a version state keeps the key in the write it already makes: creating, saving a new version,
  moving a card, publishing, publishing an older version, unpublishing and repairing a lineage cost exactly the writes they cost
  before. Superseding a row clears its key in the same update that marks it superseded, and passes the row's own `updatedAt` so the
  old row does not look freshly changed. The old `stage` attribute and index are not touched, so old readers keep working.

  `papyrus stories head-index` fills the key in on rows written before it existed. It reads the old stage index once, picks each
  lineage's head with the same rule `stories show` uses, writes only rows that differ, keeps each row's own `updatedAt`, never touches a
  superseded row, and is a dry run unless given `--apply`. Run again it changes nothing, so its dry run is also the health check.

  The CLI serves sites on different versions from one install. A site whose data API has no `headStageKey` yet is written without it,
  and the CLI says so once.

  Background:
    Given an empty newsroom backend

  Scenario: A new story is the head of its stage
    When an editor creates the story "Rivers" at the idea stage
    Then the story "Rivers" has exactly one head row, in the idea stage
    And the head row of "Rivers" carries the head stage key "idea"

  Scenario: Saving a new version moves the head to the new row in the same writes as before
    Given the story "Rivers" in copywriting with one saved version
    When an editor saves a new version of "Rivers"
    Then the story "Rivers" has exactly one head row, in the copywriting stage
    And the head row of "Rivers" is version 2
    And version 1 of "Rivers" is superseded and carries no head stage key
    And saving the version wrote one new Item row and updated one Item row

  Scenario: A superseded row keeps its own update time
    Given the story "Rivers" in copywriting with one saved version last changed at "2026-11-01T09:00:00Z"
    When an editor saves a new version of "Rivers"
    Then the update that superseded version 1 of "Rivers" kept its update time "2026-11-01T09:00:00Z"

  Scenario: Moving a card moves the head with it
    Given the story "Rivers" in copywriting with one saved version
    When an editor moves "Rivers" to the illustration stage
    Then the story "Rivers" has exactly one head row, in the illustration stage

  Scenario: Publishing makes the published row the head in the Published stage
    Given the story "Rivers" in copywriting with one saved version
    When an editor publishes the current version of "Rivers"
    Then the story "Rivers" has exactly one head row, in the published stage

  Scenario: Publishing an older version makes it the head and takes the newer draft out of the index
    Given the story "Rivers" in copywriting with two saved versions
    When an editor publishes version 1 of "Rivers"
    Then the story "Rivers" has exactly one head row, in the published stage
    And the head row of "Rivers" is version 1
    And version 2 of "Rivers" is superseded and carries no head stage key

  Scenario: Unpublishing puts the head back in Copywriting
    Given the published story "Rivers"
    When an editor unpublishes "Rivers"
    Then the story "Rivers" has exactly one head row, in the copywriting stage

  Scenario: Starring a story leaves its head where it is
    Given the story "Rivers" in copywriting with one saved version
    And an editor gave "Rivers" 4 stars
    When an editor saves a new version of "Rivers"
    Then the story "Rivers" has exactly one head row, in the copywriting stage
    And the head row of "Rivers" has 4 stars

  Scenario: Repairing a muddled lineage leaves one head
    Given the story "Rivers" whose two versions are both marked current
    When an operator repairs the versions of "Rivers"
    Then the story "Rivers" has exactly one head row, in the copywriting stage
    And the head row of "Rivers" is version 2

  Scenario: On a backend that serves several tenants the key is tenant-scoped
    Given an authoring client for the tenant "machines-on-machines" on a site whose data API has the head stage key
    When the client creates the head row of a story in copywriting
    Then the row it sends carries the head stage key "machines-on-machines#copywriting"
    And the row keeps its plain stage "copywriting"

  Scenario: A site whose data API has no head stage key yet is written without it, and the CLI says so once
    Given an authoring client on a site whose data API has no head stage key
    When the client writes two story rows that carry head stage keys
    Then neither row it sends names the head stage key
    And the CLI said once that the site has no head stage key yet
    And it asked the site for the Item fields only once

  Scenario: The backfill dry run lists what it would change and writes nothing
    Given a site with stories written before the head stage key existed:
      | story   | versions | stage       |
      | Rivers  | 3        | copywriting |
      | Bridges | 1        | idea        |
      | Tunnels | 2        | published   |
    When an operator runs the head-index backfill without --apply
    Then it reports 3 stories, 3 heads to set, 0 keys to remove and 0 already right
    And it lists the head row of each story it would change
    And it wrote nothing

  Scenario: The backfill writes one row per story, keeps update times, never touches superseded rows, and a second run changes nothing
    Given a site with stories written before the head stage key existed:
      | story   | versions | stage       |
      | Rivers  | 3        | copywriting |
      | Bridges | 1        | idea        |
      | Tunnels | 2        | published   |
    When an operator runs the head-index backfill with --apply at 5 writes a second
    Then it updated exactly the head row of each story
    And every update kept the row's own update time
    And no superseded row was written
    And it paced the writes at no more than 5 a second
    And every story has exactly one head row
    When an operator runs the head-index backfill without --apply
    Then it reports 3 stories, 0 heads to set, 0 keys to remove and 3 already right

  Scenario: A muddled lineage with two current rows: the backfill picks the newest and reports the lineage
    Given the story "Rivers" whose two versions are both marked current
    When an operator runs the head-index backfill with --apply at 5 writes a second
    Then the head row of "Rivers" is version 2
    And version 1 of "Rivers" carries no head stage key
    And it reports "Rivers" as a lineage for stories repair-versions
    And it did not change the version state of any row

  Scenario: A head whose key names the wrong stage is corrected
    Given the story "Rivers" in copywriting with one saved version
    And version 1 of "Rivers" carries the stale head stage key "idea"
    When an operator runs the head-index backfill with --apply at 5 writes a second
    Then it reports 1 stories, 1 heads to set, 0 keys to remove and 0 already right
    And the head row of "Rivers" carries the head stage key "copywriting"

  Scenario: The backfill against a site whose data API has no head stage key yet
    Given a site with stories written before the head stage key existed:
      | story   | versions | stage       |
      | Rivers  | 2        | copywriting |
    And the site's data API has no head stage key yet
    When an operator runs the head-index backfill without --apply
    Then it reports 1 stories, 1 heads to set, 0 keys to remove and 0 already right
    And it says the site's data API needs the deploy that adds the head stage index first
    When an operator runs the head-index backfill with --apply at 5 writes a second
    Then the backfill refused to write and wrote nothing
