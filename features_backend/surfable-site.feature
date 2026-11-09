Feature: A page keeps readers on the site: citations link to our own Story, and a page knows its concepts and related Stories
  Readers should not have to leave to follow a source or a topic. When a published Story is based on the Reference a Story
  cites, that Story's bibliography entry links to our Story instead of the outside page. When no Story is, the entry links
  out, opens in a new tab and carries the Lucide external-link icon; an entry that stays on the site has no icon. A page also
  learns, from the Story's relations, which public concept pages it mentions and which published Stories it is related to,
  so the site's own code can draw them. All of it is read once per projection, through indexes, never by scanning a table.
  Withdrawn or unpublished Stories count for nothing, and a Story never links to itself.

  Scenario: A cited source links to our Story that is based on it
    Given a Story that cites two sources and a published Story based on the first
    When the site renders the citing Story
    Then the first source links to the other Story and carries no icon
    And the second source links out in a new tab with the external-link icon

  Scenario: The newest published Story based on the Reference is the one linked
    Given a Story that cites a source and two published Stories based on it
    When the site renders the citing Story
    Then the first source links to the newest of the two

  Scenario: A Story never links its own citation to itself
    Given a Story that cites a source it is itself based on
    When the site renders the citing Story
    Then the source links out in a new tab with the external-link icon

  Scenario: Only accepted References count and only the Stories based on them
    Given Stories that cite, consult or are based on References, one of them not accepted
    When the relations of the published Stories are read
    Then only the accepted Reference's address is linked, to the Story based on it

  Scenario: Concepts are the public concept pages the Story mentions or is related to
    Given Stories related to concepts, one rejected, one without a public page
    When the relations of the published Stories are read
    Then each Story keeps only its accepted concepts that have a public page
    And a page lists them most used first and then by name

  Scenario: Related Stories are read in both directions and only when published
    Given two Stories related to each other by one relation and a third pointing at an unpublished Story
    When the relations of the published Stories are read
    Then each of the two is related to the other and the third is related to none

  Scenario: Related References are the accepted see-also References, newest linked first
    Given a Story that points to three accepted References linked on different days
    When the relations of the published Stories are read
    Then the Story lists them newest linked first with the note on the link

  Scenario: Only accepted References are related References
    Given a Story that points to pending, recommended, rejected and accepted References
    When the relations of the published Stories are read
    Then only the accepted Reference is listed

  Scenario: A Reference a Story only cites or consulted is not a related Reference
    Given a Story that cites, consults and is based on References without any see-also link
    When the relations of the published Stories are read
    Then the Story has no related References

  Scenario: A related Reference carries its card fields and none of the captured text
    Given a Story that points to an accepted Reference with a card image, summary and captured text
    When the relations of the published Stories are read
    Then the Reference has its title, address, host, image, summary, medium, accepted time and note and no captured text

  Scenario: A client that cannot read relations gives no related References and no error
    Given a snapshot client
    When the relations of the published Stories are read
    Then no related References are found

  Scenario: Adding a link or changing a Reference changes what the item pages are built from
    Given a published Story pointing to an accepted Reference
    When the link is removed, or the Reference is rejected or its title is edited
    Then the shared inputs of the item pages change and unchanged data leaves them the same

  Scenario: The read costs only index queries
    Given Stories with relations
    When the relations of the published Stories are read
    Then no table is listed and only the subject and object indexes are queried
