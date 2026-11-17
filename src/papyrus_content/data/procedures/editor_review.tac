-- papyrus-procedure-kind: story.editor-review
-- Editor review: a stage bot that reviews one story version against acceptance criteria.
--
-- Start it with a story-entry automation (docs/editor-agents.md, "Editor review (stage bot)"). It runs when a story enters
-- a stage, `copywriting` by default, with the version that entered. It is the same procedure for every publication: what
-- a site adds is its editorial context (mission, policy, section guidance), its editorial policies and, optionally, a brief.
--
-- Flow: the inputs tool gathers the version, its tables, its linked References, the brief, the editorial context and the
-- editorial check (rules and the Jev lane); GPT-6 Luna writes the review; the record tool normalizes it, stores it as
-- Item.metadata.editorReview and answers with the stage-bot contract {version, hold, reason}. Hold on revise or reframe
-- (the engine raises a flag review request); approve lets the engine advance the story to the automation's next stage.
-- The editor never edits the version, never moves the stage, never publishes and never writes a Message.
--
-- Register (from the site repository, or this one):
--   papyrus procedures register --file procedures/newsroom/editor_review.tac --key <site>.editor-review --dry-run --json
-- Specs: features_backend/editor-review-stage-bot.feature (the contract and the records) and
-- procedures/newsroom/tests/test_editor_review.py (this file run through Tactus with the model faked)

-- Each toolset is named after its tool because `Tool.get(name)` looks a toolset up by the name it is called with.
Toolset "papyrus_editor_review_inputs" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Toolset "papyrus_record_editor_review" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

local json = require("tactus.io.json")

-- The model is a literal: Tactus validates the agent declaration statically.
local REVIEW_MODEL = "gpt-6-luna"

editor_reviewer = Agent {
    provider = "openai",
    model = "gpt-6-luna",
    system_prompt = [[
You are the publication's editor reviewing one story version before it moves on. You decide whether it meets the brief
and the acceptance criteria; you do not rewrite it. The reply you write is a record a person can read and overrule.

Your inputs are JSON: the version (Markus body), its tables, the References linked to the story, the brief, the
editorial context (mission, policy, section guidance) and the editorial check result. If the brief is empty, the
editorial context is the brief.

Judge every criterion in `criteria`, one finding each, with status pass, fail or na:
- A failed criterion needs a note that says what is wrong and, where it helps, a quote from the version.
- Give a failed criterion severity "error" when the version cannot move on until it is fixed, "warn" when it should be
  fixed but need not stop it.
- Check the tables yourself, cell by cell, against the linked References and the story's text: the editorial check
  skips tables. A version with a table cannot get "na" on tables-verified.
- Treat a claim as supported only by what the inputs show. A link the text promises must be in the text. A date must come
  from a dated source, not from when the publication found the item. Do not assume anything you cannot see.
- Findings of the editorial check are evidence, not verdicts: use them, and do not repeat them as findings of your own.

Verdict:
- approve: every criterion passes or fails only at warn severity.
- revise: the angle and structure hold and specific things must change. Put each change in revisionNotes, in order of
  importance, as an instruction the copywriter can act on.
- reframe: the angle or the evidence does not support the story; say what it could be instead in revisionNotes.

Also give a short illustrationPlan (needed, kind, what, why) and typesettingPlan (tables on phones, figures, pull-outs,
length) as objects. They are plans for later stages, not requirements for approval.

Never invent sources, links, dates or numbers. Never publish. Never address a person in a message: write the record.
]],
    output = {
        verdict = field.string{required = true, description = "approve, revise or reframe"},
        summary = field.string{required = true, description = "Two or three sentences a person reads first"},
        findings = field.array{required = true, description = "One per criterion: {criterion, status pass|fail|na, severity error|warn|info, quote, note}"},
        revisionNotes = field.array{required = true, description = "Instructions for the copywriter; empty on approve"},
        illustrationPlan = field.object{required = true},
        typesettingPlan = field.object{required = true}
    }
}

local MAXIMUM_ATTEMPTS = 3

local function review_of(inputs)
    local message = "Review this story version. Inputs:\n" .. json.encode(inputs)
    local result = editor_reviewer({message = message})
    local attempts = 1
    while result.output == nil and attempts < MAXIMUM_ATTEMPTS do
        result = editor_reviewer({message = "Your last reply had no structured output. Reply with every declared output field now."})
        attempts = attempts + 1
    end
    if result.output == nil then
        error("the editor did not return a structured review after " .. attempts .. " attempts")
    end
    return result.output
end

Procedure {
    input = {
        story = field.string{required = true, description = "Story lineage id"},
        version = field.string{required = true, description = "Id of the version that entered the stage"},
        versionNumber = field.number{default = 0},
        stage = field.string{default = ""},
        runKey = field.string{default = ""},
        automationId = field.string{default = ""},
        hop = field.number{default = 0}
    },
    output = {
        version = field.string{required = true},
        hold = field.boolean{required = true},
        reason = field.string{required = true},
        verdict = field.string{required = true}
    },
    function(input)
        local gather = Tool.get("papyrus_editor_review_inputs")
        local record = Tool.get("papyrus_record_editor_review")

        local inputs = gather({story = input.story, version = input.version})
        local review = review_of(inputs)
        local outcome = record({
            story = input.story,
            version = input.version,
            review = review,
            model = REVIEW_MODEL,
            context_hash = inputs.editorialContext.hash
        })
        return {
            version = outcome.version,
            hold = outcome.hold,
            reason = outcome.reason,
            verdict = outcome.verdict
        }
    end
}
