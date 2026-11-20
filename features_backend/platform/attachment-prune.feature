@backend @attachment-prune
Feature: Pruning attachments deletes only what nothing owns
  Large bodies in the newsroom (a Reference's metadata, a Message's text, a procedure's source) are stored as files, each with an attachment record
  that names its owner. When an owner is deleted its attachments can be left behind. `papyrus newsroom prune-attachments` cleans them up, and because
  it deletes files it is written to err towards keeping.

  Two things are pruned: an attachment record whose owner no longer exists, together with its file, and a file under the payload prefix that no
  attachment record names. Everything else is kept. A file that a living attachment still names is kept even when an orphaned record names it too. An
  attachment whose kind of owner this command does not know is kept and listed, because the command cannot tell whether its owner exists.

  `--dry-run` reports the same counts and deletes nothing.

  Background:
    Given the newsroom has the Reference "reference-kept" and no other owner of attachments
    And these attachments are recorded
      | attachment        | owner kind | owner             | file                                  |
      | kept-metadata     | reference  | reference-kept    | newsroom/payloads/kept-metadata.json  |
      | orphaned-metadata | reference  | reference-deleted | newsroom/payloads/orphaned.json       |
    And the payload store also holds the file "newsroom/payloads/nobody-recorded-this.json"

  Scenario: An attachment whose owner is gone is deleted with its file
    When the attachments are pruned
    Then the attachment records deleted are "orphaned-metadata"
    And the files deleted include "newsroom/payloads/orphaned.json"

  Scenario: A file that no attachment record names is deleted
    When the attachments are pruned
    Then the files deleted include "newsroom/payloads/nobody-recorded-this.json"

  Scenario: An attachment whose owner exists is kept with its file
    When the attachments are pruned
    Then the attachment "kept-metadata" is still recorded
    And the file "newsroom/payloads/kept-metadata.json" is not deleted

  Scenario: A file that a living attachment still names is kept when an orphan names it too
    Given the attachment "orphaned-copy" of the reference "reference-deleted" names the file "newsroom/payloads/kept-metadata.json"
    When the attachments are pruned
    Then the attachment records deleted are "orphaned-copy, orphaned-metadata"
    And the file "newsroom/payloads/kept-metadata.json" is not deleted

  Scenario: An attachment of a kind of owner the command does not know is kept and listed
    Given the attachment "newer-kind-of-attachment" of the podcastEpisode "episode-1" names the file "newsroom/payloads/episode.json"
    When the attachments are pruned
    Then the attachment "newer-kind-of-attachment" is still recorded
    And the file "newsroom/payloads/episode.json" is not deleted
    And the prune lists "newer-kind-of-attachment" as kept because its kind of owner is unknown

  Scenario: A dry run counts what it would delete and deletes nothing
    When the attachments are pruned with "--dry-run"
    Then the prune counts 1 orphaned attachment records and 1 orphaned files
    And no attachment record and no file is deleted
    And the prune names "poetry run papyrus sections prune-attachments" as the next command
