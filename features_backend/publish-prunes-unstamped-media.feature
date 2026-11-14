Feature: Publishing a new version replaces the pictures of the version it supersedes
  When an editor publishes a newer version of a Story that is already live, the pictures the live version
  served are replaced by the new version's, so the published pictures of a Story are always exactly the
  ones its live version names. The old picture rows are the Story's own, so they are removed even when they
  were written before the site stamped its rows with its tenant: such a row is listed under the Story but
  carries no tenant, and refusing to delete it as "not in the tenant" left every later publish of that Story
  failing half way (Machines on Machines, versions 9 and 10 of "What if you wanted people to copy your software").
  A picture row that is already gone when the publish gets to it is the state the publish wanted, not a failure.
  A row that belongs to another tenant or to another Story is never touched, whatever index listed it.

  Scenario: A picture row with no tenant stamp does not stop a new version going live
    Given a Story is live and its old picture row was written without a tenant stamp
    When the editor publishes a newer version of the Story
    Then the newer version is live
    And the old picture row is gone

  Scenario: Taking a Story off the site removes its picture rows even without a tenant stamp
    Given a Story is live and its old picture row was written without a tenant stamp
    When the editor takes the Story off the site
    Then the Story has no published picture rows

  Scenario: A picture row that is already gone is not a failure
    Given a Story is live
    When the publish prunes a picture row that another publish of the Story already deleted
    Then the prune reports nothing deleted and no error

  Scenario: A picture row of another tenant is refused and kept
    Given a Story is live and a picture row listed under it belongs to another tenant
    When the publish prunes that row
    Then the prune is refused and the row is kept

  Scenario: A picture row of another Story is refused and kept
    Given a Story is live and a picture row listed under it belongs to another Story
    When the publish prunes that row
    Then the prune is refused and the row is kept
