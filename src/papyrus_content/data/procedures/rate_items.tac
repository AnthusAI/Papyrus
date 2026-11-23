-- papyrus-procedure-kind: rate_items
-- The rating agent's run for one wake (slices L1, L2 and L3: PPY-d85860, PPY-e61642, PPY-924693; definition src/papyrus_content/agent_definitions/core/rate.yaml).
--
-- Three wakes start it, all through the site's wake queue. The daily schedule reads the published Stories nobody has rated and nobody has suggested stars for,
-- by the site's head stage index, newest first. A Story's page going live (the Item change feed's stage_entered into published, after the site's quiet window)
-- rates that one Story. A Reference being accepted (the Reference change feed's accepted) rates the Stories based on it. The wake only names its subject: the run
-- re-reads each Story and skips one a person rated or that has a suggestion waiting. For each Story it asks the bulk-tier model: three stars (the default), four
-- (clearly better than the usual Story) or five, a five-star candidate. Every answer is a suggestion for a person, never a rating. What it may write is the site's
-- agent policy, answered by the one gate: at the rung observe it writes nothing and records what it would suggest and why; at the rung propose it writes each
-- suggestion beside the Story's rating and adds it to the day's one soft review. It never writes a rating and never publishes. The run ends `acted` (with the
-- counts) or `nothing` (reason nothing_unrated).
--
-- It runs only on an agent's wake adopted as the responsibility "rate": `papyrus automations adopt --id rate --responsibility rate`. The model work is in the
-- tool (papyrus_content/rating_agent.py), which reports each call's usage to the run, so the run's cost counts it.
-- Specs: features_backend/agents/rating-agent.feature, features_backend/agents/rating-suggestion-triggers.feature

Toolset "papyrus_rate_items" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        story = field.string{default = "", description = "The Story's lineage id, from a Story's wake; empty on the schedule and on a Reference's wake"},
        change = field.string{default = "", description = "stage_entered (a Story's page went live) or accepted (a Reference was accepted), from the wake; empty on the schedule"},
        what = field.string{default = "", description = "What changed, as the wake key names it"},
        stage = field.string{default = "", description = "The stage the Story entered, from the wake"},
        subject = field.object{required = false, description = "The record a Reference's wake is about: kind Reference and its lineage id"}
    },
    output = {
        summary = field.string{required = true, description = "One sentence: how many Stories it looked at, what it proposed and suggested, or why a wake found nothing to judge"},
        result = field.object{required = true, description = "What woke it, the counts, each proposal with its reason, the five-star candidates, the Stories skipped and why, what could not be judged and the gate's answers"},
        run_outcome = field.string{description = "acted, or nothing when no Story waits for a rating; the runner records it"},
        run_outcome_reason = field.string{description = "proposed, suggested or nothing_unrated"}
    },
    function(input)
        local rate = Tool.get("papyrus_rate_items")
        local subject = input.subject or {}
        local result = rate({story = input.story, change = input.change, what = input.what, stage = input.stage,
                             subject_kind = subject.kind or "", subject_id = subject.id or ""})
        return {summary = result.summary, result = result, run_outcome = result.run_outcome, run_outcome_reason = result.run_outcome_reason}
    end
}
