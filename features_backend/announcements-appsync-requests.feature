Feature: Every call the Announcements page makes reaches its operation in the function
  The page calls the announcements function through the site's GraphQL API. Amplify's function resolver hands the Lambda
  the GraphQL field at the top of the request as "fieldName", next to the arguments and the caller's identity; it sends no
  "info" object. The function takes the operation from that field, in one place, so every page call runs the operation
  it names. A request that names no field is refused in plain words, never as an unknown operation with no name.

  Background:
    Given a site "mom" with a fake X and encrypted parameter storage
    And the announcements function is running with that site's tables and the fake X

  Scenario: Each page call, sent as Amplify sends it, runs the operation it names
    When an admin "ryan" makes these page calls in order, each as the request Amplify sends
      | page call               | type     | field                     |
      | read the settings       | Query    | announcementsSettings     |
      | read the X status       | Query    | announcementsXStatus      |
      | save the X app keys     | Mutation | announcementsXSaveApp     |
      | begin connecting X      | Mutation | announcementsXBegin       |
      | complete connecting X   | Mutation | announcementsXComplete    |
      | read the X usage        | Query    | announcementsXUsage       |
      | save the settings       | Mutation | announcementsSaveSettings |
      | pause announcements     | Mutation | announcementsPause        |
      | disconnect X            | Mutation | announcementsXDisconnect  |
    Then every call answered ok with what its operation returns
      | field                     | answer holds  |
      | announcementsSettings     | settings      |
      | announcementsXStatus      | status        |
      | announcementsXSaveApp     | status        |
      | announcementsXBegin       | authorizeUrl  |
      | announcementsXComplete    | status        |
      | announcementsXUsage       | usage         |
      | announcementsSaveSettings | settings      |
      | announcementsPause        | settings      |
      | announcementsXDisconnect  | status        |
    And the saved settings show announcements paused by "ryan"

  Scenario: An editor's read reaches its operation and an editor's change is refused by role, not by name
    When an editor "ellie" reads the X status as the request Amplify sends
    Then the answer is ok and holds "status"
    When an editor "ellie" tries to pause announcements as the request Amplify sends
    Then the answer is refused with "forbidden"

  Scenario: A request that names no operation says so
    When a request with no GraphQL field reaches the announcements function
    Then the request is refused as "no_operation" with the message "The request carried no operation: it named no GraphQL field."
    And no answer says "Unknown operation ."
