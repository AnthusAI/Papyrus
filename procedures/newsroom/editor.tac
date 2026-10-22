-- Papyrus automated newsroom editor procedure.
--
-- Dry-run only: this procedure returns assignment Item, EditionItem, and
-- downstream reporter dispatch plans but does not write to GraphQL.

local done = require("tactus.tools.done")

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_editor = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You are the Papyrus newsroom editor agent.

Goal:
- Dispatch article assignments for one edition.
- Use execute_tactus as your only tool for Papyrus, Biblicus, context, and dry-run plan work.
- Inside execute_tactus, compose Papyrus APIs with short Tactus snippets.
- Use live desk and focus-topic context when the input names explicit focus work.
- Use section targets to dispatch more assignments than final slots at a bounded ratio.
- Use plan_assignment_dispatch for the assignment list.

Rules:
- This is dry-run only. Never claim records were written.
- Assignment records must use Item.type = "assignment" and Item.status = "dispatched".
- Default to an overassignment ratio of 3/2 unless the input says otherwise.
- Prefer desk and focus-topic metadata over hard-coded track templates when the input provides them.
- Return one reporter dispatch input for each assignment Item so downstream reporter agents can run independently.
- Avoid repeating recent published article angles.
- Return structured data with assignments, dry-run record plans, reporter dispatches, reviewer load, and a concise summary.
]],
    tools = {"papyrus", done},
    output = {
        edition_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        assignment_ratio = field.string{required = true},
        section_targets = field.array{required = true},
        assignments = field.array{required = true},
        record_plans = field.array{required = true},
        reporter_dispatches = field.array{required = true},
        reviewer_load = field.object{required = true},
        summary = field.string{required = true}
    }
}

Procedure {
    input = {
        edition_id = field.string{required = true, description = "Papyrus Edition.id to plan assignments for"},
        corpus_key = field.string{required = true, description = "Papyrus steering corpus key"},
        context_profile = field.string{default = "", description = "Optional live context profile override"},
        section_targets_json = field.string{default = "", description = "JSON object or array of section article targets"},
        assignment_ratio = field.string{default = "1.5", description = "Assignment-to-final-slot ratio. Default 3/2."},
        max_assignments = field.integer{default = 3, description = "Fallback final-slot target when section_targets_json is empty"},
        recent_days = field.integer{default = 30, description = "Published article lookback window"}
    },
    output = {
        edition_id = field.string{required = true},
        corpus_key = field.string{required = true},
        dry_run = field.boolean{required = true},
        assignment_ratio = field.string{required = true},
        section_targets = field.array{required = true},
        assignments = field.array{required = true},
        record_plans = field.array{required = true},
        reporter_dispatches = field.array{required = true},
        reviewer_load = field.object{required = true},
        summary = field.string{required = true}
    },
    function(input)
        local section_targets_json = input.section_targets_json
        if section_targets_json == "" then
            section_targets_json = string.format([[
[{"section":"News","target_articles":%d}]
]], input.max_assignments)
        end
        local message = string.format([[
Create assignment dispatch plans for edition %s using corpus %s.

Section targets JSON:
%s

Assignment ratio:
%s

Required tool flow:
1. Call execute_tactus with one short Tactus snippet.
2. In that snippet, use edition_get, edition_items, recent_published_articles, and biblicus_steering_artifacts.
3. Use biblicus_topic_context or biblicus_query for evidence.
4. Propose candidate assignments for each section, with a few extra candidates only if needed.
5. Use plan_assignment_dispatch once with edition_id, corpus_key, section_targets_json, assignment_ratio, and assignments_json.

Return dry_run=true, assignment_ratio, section_targets, assignments, record_plans,
reporter_dispatches, reviewer_load, and a concise summary.
]], input.edition_id, input.corpus_key, section_targets_json, input.assignment_ratio)

        local result = newsroom_editor({message = message})
        return result.output
    end
}

Specification([[
Feature: Newsroom editor procedure
  The editor creates dry-run assignment dispatch plans without live writes.

  Scenario: Editor returns assignment plans
    Given the procedure has started
    And the input edition_id is "edition-2026-05-16"
    And the input corpus_key is "AI-ML-research"
    And the input context_profile is "reporting"
    And the input section_targets_json is "[{\"section\":\"Research\",\"target_articles\":1}]"
    And the input assignment_ratio is "1.5"
    And the input recent_days is 14
    And the agent "newsroom_editor" calls tool "execute_tactus" with args {"tactus": "local edition = edition_get{ id = \"edition-2026-05-16\" }; local items = edition_items{ id = \"edition-2026-05-16\" }; local recent = recent_published_articles{ recent_days = 14 }; local steering = biblicus_steering_artifacts{ corpus_key = \"AI-ML-research\" }; return { edition = edition, items = items, recent = recent, steering = steering }"}
    And the agent "newsroom_editor" returns data {"edition_id":"edition-2026-05-16","corpus_key":"AI-ML-research","dry_run":True,"assignment_ratio":"1.5","section_targets":[{"section":"Research","targetArticles":1,"dispatchCount":2}],"assignments":[{"title":"AI Agents Enter the Lab","slug":"ai-agents-enter-the-lab","type":"assignment"}],"record_plans":[{"dryRun":True,"lifecycle":"assignment-dispatch","records":[{"modelName":"Item","action":"create","input":{"type":"assignment","status":"dispatched","typeStatus":"assignment#dispatched"}}]}],"reporter_dispatches":[{"procedure":"procedures/newsroom/reporter.tac","assignmentItemId":"assignment-abc123"}],"reviewer_load":{"targetArticleCount":1,"dispatchedAssignmentCount":2,"assignmentRatio":1.5},"summary":"Created two dry-run assignment dispatch plans for one planned Research slot."}
    When the procedure runs
    Then the procedure should complete successfully
    And the output dry_run should be true
    And the output assignment_ratio should be "1.5"
    And the output assignments should exist
    And the output record_plans should exist
    And the output reporter_dispatches should exist
]])
