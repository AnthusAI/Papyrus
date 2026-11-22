-- papyrus-procedure-kind: review_deadline
-- The engine's run for a soft review's deadline (PPY-9b8e59, slice C3 of docs/design/always-on-agents-architecture.md).
--
-- A soft review with a deadline sets one follow-up timer (src/papyrus_content/review_deadline_timers.py). At the deadline the timer puts one wake on the site's
-- queue and the procedure runner starts this, with no adopted agent: the engine's own follow-ups are not an agent's work, and only the site's pause stops them
-- (src/papyrus_content/engine_follow_ups.py). It reads the request again and, only if it still waits for exactly that deadline, records "proceeded without
-- review" in one conditional write. An answer, a withdrawal or a moved deadline before the wake means it does nothing. The run ends `acted` (reason timed_out)
-- or `nothing` (reason not_waiting). It calls no model and never answers, approves or publishes anything.
-- Specs: features_backend/stories/review-deadline-timers.feature

Toolset "papyrus_review_deadline" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        reviewRequestId = field.string{required = true, description = "The review request whose deadline came"},
        dueAt = field.string{required = true, description = "The deadline the wake was set for, a UTC instant"}
    },
    output = {
        summary = field.string{required = true, description = "One sentence: whether the request proceeded without review, or why nothing was done"},
        result = field.object{required = true, description = "What the wake did and why"},
        run_outcome = field.string{description = "acted, or nothing when the request no longer waited for that deadline; the runner records it"},
        run_outcome_reason = field.string{description = "timed_out or not_waiting"}
    },
    function(input)
        local deadline = Tool.get("papyrus_review_deadline")
        local result = deadline({review_request_id = input.reviewRequestId, due_at = input.dueAt})
        return {summary = result.summary, result = result.result, run_outcome = result.run_outcome, run_outcome_reason = result.run_outcome_reason}
    end
}
