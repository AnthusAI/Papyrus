-- Papyrus optional / rotating desk selector (edition planning step 2).
--
-- Run after phase-1 theme proposals are accepted. The agent should review
-- recent optional-desk usage and recommend one floating or rotating desk for
-- the edition without repeating the same desk every cycle.

local done = require("tactus.tools.done")

Toolset "papyrus" {
    type = "plugin",
    paths = {"./procedures/newsroom/tactus_tools"}
}

newsroom_rotating_section_selector = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You are the Papyrus rotating-desk selector for edition planning step 2.

Goal:
- Recommend exactly one optional desk (floating or rotating NewsroomSection) for the edition.
- Use execute_tactus as your only tool.
- Read recent optional-desk usage so the newsroom does not repeat the same desk every edition.
- Treat the accepted edition theme as fixed input from phase 1.

Rules:
- Propose one desk for forum review; do not treat it as locked unless the input says the edition is locked.
- Prefer desks that complement the accepted theme and have not appeared in the most recent editions unless there is a strong reason to repeat.
- Explain why recent usage matters and which desks were avoided.
- Do not replace canonical desks; this step only selects the optional / rotating desk.
]],
    tools = {"papyrus", done},
    output = {
        edition_id = field.string{required = true},
        accepted_theme = field.string{required = true},
        recommended_section_key = field.string{required = true},
        recommended_section_title = field.string{required = true},
        recommendation_summary = field.string{required = true},
        avoided_sections = field.array{required = true},
        recent_usage = field.array{required = true},
        rationale = field.string{required = true}
    }
}

Procedure {
    input = {
        edition_id = field.string{required = true, description = "Edition.id for the planning edition"},
        accepted_theme = field.string{required = true, description = "Accepted edition theme from phase 1"},
        coverage_key = field.string{default = "", description = "Coverage concept key from phase 1"},
        candidate_sections_json = field.string{default = "[]", description = "JSON array of optional desk candidates"},
        recent_usage_json = field.string{default = "[]", description = "JSON array of recent optional-desk usage rows"},
        steering_notes = field.string{default = "", description = "Optional human steering from the edition forum"}
    },
    output = {
        edition_id = field.string{required = true},
        accepted_theme = field.string{required = true},
        recommended_section_key = field.string{required = true},
        recommended_section_title = field.string{required = true},
        recommendation_summary = field.string{required = true},
        avoided_sections = field.array{required = true},
        recent_usage = field.array{required = true},
        rationale = field.string{required = true}
    },
    function(input)
        local message = string.format([[
Select one optional / rotating desk for edition %s.

Accepted theme: %s
Coverage key: %s
Candidate desks JSON: %s
Recent optional-desk usage JSON: %s
Human steering notes: %s

Return structured output with one proposed desk, sections to rotate away from when recent_usage_json is non-empty, and a short rationale suitable for a forum follow-up post. If recent_usage_json is [], do not invent prior editions.
]], input.edition_id, input.accepted_theme, input.coverage_key, input.candidate_sections_json, input.recent_usage_json, input.steering_notes)
        return newsroom_rotating_section_selector{message = message}
    end
}
