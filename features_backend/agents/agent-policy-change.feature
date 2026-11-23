Feature: Only a person signed in to the console changes the agent policy
  The agent policy says how far each always-on agent may go and how much paid agent work may spend. A rung or a budget is a person's decision, never
  an agent's, and an agent working in a person's session holds that person's credentials. So a signed-in admin does not write the policy with their own
  credentials: every change, a rung, a pause, a loop limit or the budget, goes to the site's agent-policy function. The function checks that the token
  belongs to an admin and was issued to a person-only app client (the console's), and only then saves the version with its own role, recording who,
  when and why. A token issued to any other client is refused and nothing is saved, whichever command sent it. The admin group may read the policy
  objects but not write them, so the function is the only way in. Releasing the wakes that wait for the budget still needs the operator's
  credentials for the site's wake queue, as before.

  That holds for the policy's catalogue rows as much as for its body. The policy's rows sit in the same two models as every other site document
  (SiteDocument and SiteDocumentVersion), and the data API's rules can say who may write a model, not which kind of row. So the admin group reads
  those models and writes none of them, of any kind: the agent policy is written by the function's role, and the listener index by the deploy's
  role, which the data API admits by its own IAM policy rather than by these rules. No console page writes a site document, so nothing a person
  edits is lost. A person's session that tries to write the listener index is told to leave it to the deploy before anything is read.

  Background:
    Given a site whose agent policy holds "rate" at the rung "propose" and a budget of 5 dollars a week, changed only through the policy function

  Scenario: A person on the console's client raises a rung, and the version records who and when
    When ada, an admin signed in on the console's app client, sets "rate" to the rung "observe" because "Watch it for a week"
    Then the policy function saved version 2 with "rate" at the rung "observe"
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Watch it for a week"

  Scenario: A credential issued to another app client cannot change a rung
    When an agent holding an admin token from another app client sets "rate" to the rung "observe" because "Raise myself"
    Then the policy function refused the change as "human_required"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  Scenario: A person on the console's client raises the budget with set-budget, and the version records who and when
    When ada, an admin signed in on the console's app client, runs set-budget for 20 dollars a week because "Launch week" and applies it
    Then the budget command succeeded and saved version 2
    And the agent policy holds a budget of 20 dollars a week at version 2
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Launch week"

  Scenario: A credential issued to another app client cannot change the budget
    When an agent holding an admin token from another app client runs set-budget for 500 dollars a week because "More room" and applies it
    Then the budget command was refused as "human_required"
    And the agent policy holds a budget of 5 dollars a week at version 1

  Scenario: The signed-in commands write nothing to the policy objects themselves
    When ada, an admin signed in on the console's app client, runs set-budget for 20 dollars a week because "Launch week" and applies it
    Then the signed-in command's own credentials wrote no policy object and no catalogue row
    And every policy object was written by the policy function

  Scenario: With no person-only client configured, nobody changes the policy
    Given the site's stack names no person-only app client
    When ada, an admin signed in on the console's app client, sets "rate" to the rung "observe" because "Watch it for a week"
    Then the policy function refused the change as "human_required"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  # The newsroom's Announcements settings page sets how X story posts are reviewed through this same function: the review is the announce
  # rung of this document, narrowed to the channel x and the kind story_published, and the console never writes the policy any other way.
  Scenario: A person on the console's client sets X story posts to soft review, and reads it back
    When ada, an admin signed in on the console's app client, sets the review of X story posts to "soft" because "Set in the newsroom's Announcements settings."
    Then the policy function saved the review as version 2, with "announce" at the rung "publish_soft" for the channel "x" and the kind "story_published"
    And version 2 of the agent policy records "ada@example.test", the time "2026-11-22T09:00:00Z" and the reason "Set in the newsroom's Announcements settings."
    And ada, reading the review of X story posts on the console's app client, sees "soft"

  Scenario: A credential issued to another app client cannot set the review of X story posts
    When an agent holding an admin token from another app client sets the review of X story posts to "soft" because "Post without asking"
    Then the policy function refused the review as "human_required"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  Scenario: A caller that says it is an agent is blocked, even on the console's client
    When an agent declaring itself on the console's app client sets the review of X story posts to "hard" because "Tidy up"
    Then the policy function refused the review as "blocked"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  Scenario: Posts right away is refused while the hard floor stands
    When ada, an admin signed in on the console's app client, sets the review of X story posts to "none" because "Go straight out"
    Then the policy function refused the review as "constraint_conflict"
    And the agent policy is still version 1 with "rate" at the rung "propose"

  Scenario: The admin group reads the site documents' catalogue and writes none of it
    When the data API's rules for "SiteDocument" and "SiteDocumentVersion" are read from the deployed schema and the typed schema
    Then in both schemas the admin group may only read each of the two models
    And no rule of either model in either schema lets a group or an owner create, update or delete a row

  Scenario: A signed-in admin cannot write the listener index; the deploy's own role does
    When ada, signed in to the site, runs "papyrus agents listeners" to write the listener index
    Then the listeners command was refused as "not_authorized", naming the deploy's own role
    And the command read no site document and wrote no object and no catalogue row
    When the deploy runs "papyrus agents listeners" as its own role
    Then the listener index is at version 1, and every object and catalogue row of it was written by the deploy's role
