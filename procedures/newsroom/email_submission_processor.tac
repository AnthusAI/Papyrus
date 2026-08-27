-- papyrus-procedure-kind: submissions.email.process
-- Process inbound email submissions: create, find, and process direct citations only.
--
-- The outer SES/Message workflow stores the email as a Message. This procedure
-- reads that Message, rejects research-assignment-style requests, and runs the
-- reference create/find/process pipeline for explicit URLs and DOIs.

Procedure {
    input = {
        message_id = field.string{required = true, description = "Inbound email Message.id"},
        corpus_key = field.string{default = "threat-intelligence", description = "Target steering corpus key"},
        apply = field.boolean{default = true, description = "When false, build plans without GraphQL writes"}
    },
    output = {
        result = field.object{required = true}
    },
    function(input)
        local response = papyrus_email_submission_process{
            message_id = input.message_id,
            corpus_key = input.corpus_key or "threat-intelligence",
            apply = input.apply ~= false,
        }
        return {
            result = response,
        }
    end
}
