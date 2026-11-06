Feature: An agent on the signed-in CLI accepts, rejects and rates as the signed-in editor, with no delegation; delegations stay optional
  An editor or administrator can ask an agent to help them curate References: "accept that one with four stars". The agent works in the
  editor's own signed-in `papyrus` session and acts directly as that person: its accepts, rejects and star ratings are recorded as the
  editor's own decisions, with a plain note of where they came from (`via cli`, and the agent's name if it gives one). Nothing requires a
  delegation, a code or an approval step, and the note is never a gate. Only the editor and administrator groups may do it.
  A delegation is still available, optionally, for anyone who wants it: the editor's permission for an agent to relay decisions, approved by
  the editor in the Newsroom with a short code, lasting a limited number of hours, naming the agent, and revocable at any time. Because an
  agent's session is the editor's own, the Newsroom tells the sessions apart by the sign-in client the token was issued to (cliOnFederationClient),
  so a session cannot approve its own delegation request. A relayed decision names the agent and the delegation. Nothing here touches a real
  site, login, network or AWS; the Newsroom's backend function runs against an in-memory data client.

  Scenario: An agent asks for a delegation from a signed-in session with no AWS login
    Given the CLI is signed in to a site and has no AWS credentials
    When the agent asks for a two hour delegation as "Claude"
    Then the request goes with the session's token and no AWS signature
    And the agent is given an approval code and a private file holds the secret
    And the agent is told that only a person in the Newsroom can approve it
    And the CLI has no command that approves a delegation

  Scenario: After the editor approves the code in the Newsroom the agent relays an accept, a reject and a star rating
    Given the CLI is signed in to a site and has no AWS credentials
    And the agent holds a delegation file that the editor approved
    When the agent relays an approve, a reject and a four star rating for the editor
    Then the three decisions are sent with the delegation file's secret and the session's token
    And the approve is recorded as an accept
    And the Newsroom records the agent's request, the editor's approval and the relayed decisions

  Scenario: A request that no person has approved records nothing
    Given a site that signs its CLI in on its own client
    When the agent asks for a delegation from a signed-in session
    Then the request waits for a person's approval
    And a decision relayed under it is refused as not approved by a person
    And the Reference keeps its vote and rating

  Scenario: A signed-in session cannot approve its own delegation request
    Given a site that signs its CLI in on its own client
    And the agent asked for a delegation from a signed-in session
    When the same editor's CLI session tries to approve the code, create a delegation or list the pending codes
    Then each attempt is refused because approval belongs to the Newsroom
    And the request is still waiting
    And the editor's approval in the Newsroom is accepted

  Scenario: A site that has not separated the CLI from the Newsroom refuses signed-in requests
    Given a site that signs its CLI in on the same client as the Newsroom
    When a signed-in session asks for a delegation or relays a decision
    Then it is refused with the setting the site needs
    And no delegation is stored
    And an operator on AWS credentials can still ask and the Newsroom still approves

  Scenario: Only editors and administrators can ask, approve or relay
    Given a site that signs its CLI in on its own client
    When a reader, or a person in no group, asks for a delegation, approves a code or relays a decision
    Then each is refused as not an editor or administrator
    And the Reference keeps its vote and rating

  Scenario: The hours limit and the expiry hold
    Given a site that signs its CLI in on its own client
    When the agent asks for no hours, a negative number of hours or more than seventy-two hours
    Then the request is refused and no delegation is stored
    And an approved delegation lasts exactly the hours asked for
    And a relayed decision after it expires is refused

  Scenario: The editor can revoke a delegation and the agent can withdraw its own request
    Given a site that signs its CLI in on its own client
    When the editor revokes an approved delegation after the agent relayed a decision
    Then nothing more is recorded under it
    And the agent's own session can deny or withdraw a pending request
    And an editor who did not grant a delegation cannot revoke it

  Scenario: A delegation works only for its agent, its editor and its own site
    Given a site that signs its CLI in on its own client
    And the agent asked for a delegation and the editor approved its code in the Newsroom
    When another agent name, another person's name, a guessed secret or another site's backend is used with it
    Then each is refused and nothing is recorded

  Scenario: A relayed decision names the agent and the delegation and is not the editor's own direct action
    Given a site that signs its CLI in on its own client
    And the agent asked for a delegation and the editor approved its code in the Newsroom
    When the agent relays an accept and a four star rating
    Then the vote records the delegation, the agent and the editor's words
    And the rating is filed as the editor's rating relayed by the agent under that delegation
    And the audit record keeps the agent's name, the approver and the editor whose session asked

  Scenario: A direct vote from a signed-in CLI session is the editor's own, with a plain note of where it came from
    Given a site that signs its CLI in on its own client
    When a CLI session votes without a delegation and a Newsroom session votes
    Then both are recorded as the person's vote, and the CLI's carries a note that it came through the CLI and the agent's name

  Scenario: A relayed rating follows the rules of the Newsroom's own rating
    Given a site that signs its CLI in on its own client
    When the agent relays ratings from zero to six, a half star, a four, a five and a clear
    Then ratings outside one to five are refused and write nothing
    And the newest rating wins and a clear removes who and when
    And rating a pending Reference accepts it as the editor's decision relayed by the agent, and a rating never changes an accept or reject already made

  Scenario: An agent accepts and rates as the signed-in editor with no delegation at all
    Given the CLI is signed in to a site and has no AWS credentials
    When the agent approves a Reference and rates another with the plain commands
    Then the session's token carries an accept and a rating that name the agent, with no delegation anywhere

  Scenario: The command refuses a bad rating and a dry run sends nothing
    Given the CLI is signed in to a site and has no AWS credentials
    When the agent runs set-stars with a rating outside one to five, with a dry run, and with help
    Then no request is sent for any of them

  Scenario: A token whose sign-in client cannot be read can do nothing with delegations
    Given a site that signs its CLI in on its own client
    And the agent asked for a delegation from a signed-in session
    When an editor's token that names no sign-in client tries to approve, create, list, deny, revoke, ask or check a delegation
    Then each attempt is refused because the client could not be read
    And the request is still waiting for the Newsroom

  Scenario: A signed-in CLI session rates as the editor without a delegation
    Given a site that signs its CLI in on its own client
    When a CLI session sets a Reference or Story rating directly, naming the editor as the rater
    Then both ratings are saved as the editor's, with a note that they came through the CLI
    And a Newsroom session's own rating and a delegated rating still work

  Scenario: An editor's session cannot forge an approved delegation through the models it can write
    Given a site that signs its CLI in on its own client
    When an editor's session makes a payload row and attaches an approved delegation record to it, or overwrites a pending request's old file
    Then the agent's decision under it is refused as not recognized or not approved
    And a real delegation that the editor approved in the Newsroom still works
    And only the Newsroom's own function can write the delegation records

  Scenario: Delegation routes grant no rule to a signed-in reader
    When the deployed authorization of the delegation routes is read
    Then the agent routes allow the operator lane and the editor and admin groups
    And the person routes allow the editor and admin groups only
