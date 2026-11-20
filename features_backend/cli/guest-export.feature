Feature: A reader build exports published content as a guest, with no credentials
  A static reader build has no credentials of its own. It exports published content as a guest of the site's Cognito identity
  pool, signing each request with the guest identity. The guest lane can only read, and only what is published: drafts are
  refused, and every command other than the published export refuses the lane.

  Scenario: Guest export refuses drafts
    When I run export-published with auth guest and drafts
    Then the command is refused with "cannot be combined with --drafts"

  Scenario: Other commands refuse the guest lane
    Given the environment selects guest auth
    When I create an authoring client for a write command
    Then the command is refused with "only valid for 'content export-published'"

  Scenario: Guest requests are signed with the unauthenticated identity credentials
    Given a stubbed identity pool that issues guest credentials
    When I sign an AppSync request as a guest
    Then the request is signed for the appsync service with the guest session token
