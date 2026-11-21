Feature: An admin sets an agent's rung with papyrus agents set-rung
  How far an always-on agent may go on a site is one line of the site's agent policy document, and a person raises or lowers it with
  "papyrus agents set-rung". The rung is a decision that belongs to a person: only an admin who is a person may set one, always with a reason, and an
  agent is blocked from it at every rung. The command is a dry run unless it is given --apply, and prints the agent's policy entry before and after and
  the version the change is. Applying it saves a new version of the policy, so the old versions stay as the history. It refuses a rung that is not on the
  ladder, a rung above the highest one the agent's definition needs (a higher rung would allow it nothing more), and publish_auto while a hard floor
  forbids it: doubt must stop automatic publishing at every rung, and the gate that enforces that is not built yet. The runner reads the saved version
  at its next wake, so a change takes effect without a deploy.

  Scenario: The command is a dry run until it is given --apply
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "observe" because "Watch it for a week"
    Then the command succeeds as a dry run
    And it shows "rate" before as not named at policy version 0
    And it shows "rate" after at "observe" as policy version 1
    And the site's policy is still version 0

  Scenario: Applying saves a new version that says who, when and why
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "observe" because "Watch it for a week" and applies it
    Then the command succeeds and applied the change
    And the site's policy is version 1 and "rate" is at "observe"
    And version 1 records the admin "ada" and the reason "Watch it for a week"

  Scenario: Raising the rung again keeps the history
    Given a site where "rate" was set to "observe" with the command
    When an admin runs set-rung for "rate" to "draft" because "Its proposals held up" and applies it
    Then it shows "rate" before at "observe" as policy version 1
    And it shows "rate" after at "draft" as policy version 2
    And version 1 of the policy still holds "rate" at "observe"

  Scenario: Lowering the rung is the same command
    Given a site where "rate" was set to "draft" with the command
    When an admin runs set-rung for "rate" to "observe" because "Too many wrong threes" and applies it
    Then the site's policy is version 2 and "rate" is at "observe"

  Scenario: A rung the agent already has writes nothing
    Given a site where "rate" was set to "observe" with the command
    When an admin runs set-rung for "rate" to "observe" because "Again" and applies it
    Then the command succeeds and said nothing changed
    And the site's policy is version 1 and "rate" is at "observe"

  Scenario: A rung can be set for one scope only
    Given a site where "rate" was set to "observe" with the command
    When an admin applies set-rung to "propose" for "rate" within the scope "section=security" because "Start with one section"
    Then the site's policy is version 2 and "rate" is at "observe"
    And "rate" is at "propose" for the section "security"

  Scenario: A rung that is not on the ladder is refused
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "turbo" because "Faster" and applies it
    Then the command is refused as invalid input saying the rung must be one of the ladder
    And the site's policy is still version 0

  Scenario: An agent that does not exist is refused
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "poet" to "observe" because "Try it" and applies it
    Then the command is refused as invalid input naming the agents there are
    And the site's policy is still version 0

  Scenario: A rung above what the definition allows is refused
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "prepare" because "More" and applies it
    Then the command is refused as a constraint conflict saying the rating agent needs no more than "draft"
    And the site's policy is still version 0

  Scenario: The highest rung the definition needs is allowed
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "draft" because "Its operations need draft" and applies it
    Then the command succeeds and applied the change
    And the site's policy is version 1 and "rate" is at "draft"

  Scenario: publish_auto is refused while a hard floor forbids it, even when the definition asks for it
    Given a site with no agent policy saved yet
    And a site definition "rate-everything" whose operations reach publish_auto
    When an admin runs set-rung for "rate-everything" to "publish_auto" because "Fully automatic" and applies it
    Then the command is refused as a constraint conflict saying a hard floor forbids publish_auto
    And the site's policy is still version 0

  Scenario: A reason is required
    Given a site with no agent policy saved yet
    When an admin runs set-rung for "rate" to "observe" with no reason
    Then the command is refused as invalid input asking for --reason
    And the site's policy is still version 0

  Scenario: An editor cannot set a rung
    Given a site with no agent policy saved yet
    When an editor runs set-rung for "rate" to "observe" because "Let me" and applies it
    Then the command is refused as not authorized
    And the site's policy is still version 0

  Scenario: An editor cannot even preview a rung change
    Given a site with no agent policy saved yet
    When an editor runs set-rung for "rate" to "observe" because "Let me see" 
    Then the command is refused as not authorized

  Scenario: An agent is blocked at every rung
    Given a site where "rate" was set to "draft" with the command
    When an agent runs set-rung for "rate" to "off" because "Quieter" and applies it
    Then the command is refused as blocked
    And the site's policy is version 1 and "rate" is at "draft"

  Scenario: An agent in an admin's session may set a rung up to prepare on that person's instruction, and the record names both
    Given a site with no agent policy saved yet
    When an agent in ada's session sets "rate" to "draft" on the instruction of "ada" who said "turn the rating agent on"
    Then the command succeeds and applied the change
    And the policy version 1 says it was saved by "ada via cli (Claude)" and its reason holds "entered by Claude on the instruction of ada"
    And the policy version 1 says it was saved by "ada via cli (Claude)" and its reason holds "turn the rating agent on"

  Scenario: An agent may not name someone other than the person whose session it runs in
    Given a site with no agent policy saved yet
    When an agent in ada's session sets "rate" to "draft" on the instruction of "bea" who said "do it"
    Then the command is refused as not authorized
    And the site's policy is still version 0

  Scenario: An agent in an editor's session cannot change the policy on anyone's instruction
    Given a site with no agent policy saved yet
    When an agent in ed's session sets "rate" to "draft" on the instruction of "ed" who said "do it"
    Then the command is refused as not authorized

  Scenario: An agent that names no one is blocked as before
    Given a site with no agent policy saved yet
    When an agent in ada's session sets "rate" to "draft" without naming anyone
    Then the command is refused as blocked
    And the site's policy is still version 0

  Scenario: An agent may not raise a rung above prepare, whoever told it to
    Given a site with no agent policy saved yet
    When an agent in ada's session sets "announce" to "publish_soft" on the instruction of "ada" who said "go all the way"
    Then the command is refused as blocked
    And the site's policy is still version 0

  Scenario: A change made while another admin saved is refused, not overwritten
    Given a site with no agent policy saved yet
    And another admin saves the policy while the change is being made
    When an admin runs set-rung for "rate" to "observe" because "Watch it" and applies it
    Then the command is refused as a stale version
    And the policy holds only the other admin's version

  Scenario: The runner starts the agent under the new rung at its next wake
    Given a site where "rate" was set to "observe" with the command
    Then a wake for "rate" starts under policy version 1 at the rung "observe"

  Scenario: An agent the policy does not name stays off
    Given a site where "rate" was set to "observe" with the command
    Then a wake for "improve" starts nothing and says "improve is off"

  Scenario: Every request the policy store sends is one the site's GraphQL schema accepts
    The fake site API above answers whatever the store sends, so a request AppSync would refuse can pass every scenario here and fail on a real site: an
    unknown input field was exactly that (the conditions of a create named "id", which no model's condition input has; AppSync's create already refuses an
    existing key). The requests of a first save, a second save with its conditional update, and a dry run are checked against the schema Amplify
    generates from amplify/data/schema.ts, with the same transformers a deployment uses: each request must validate, and its variables must fit the input
    types it declares.
    Given a site where "rate" was set to "observe" with the command
    When an admin runs set-rung for "rate" to "draft" because "Its proposals held up" and applies it
    And an admin runs set-rung for "rate" to "observe" because "Looking again"
    Then every request the site store sent is accepted by the GraphQL schema Amplify generates from the data schema
    And the requests include a conditional update, a create and a latest-version query
