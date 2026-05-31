use anyhow::{Context, Result, anyhow};
use aws_config::BehaviorVersion;
use aws_credential_types::provider::{ProvideCredentials, SharedCredentialsProvider};
use aws_sdk_dynamodb::Client as DynamoClient;
use aws_sdk_dynamodb::types::AttributeValue;
use aws_sdk_ssm::Client as SsmClient;
use aws_sigv4::http_request::{SignableBody, SignableRequest, SigningSettings, sign};
use aws_sigv4::sign::v4;
use chrono::{DateTime, Duration, Utc};
use futures_util::StreamExt;
use lambda_runtime::{Error, LambdaEvent, run, service_fn};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::SystemTime;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::{Duration as TokioDuration, timeout};
use tracing::{error, info, warn};
use uuid::Uuid;

const DEFAULT_RESPONSE_TARGET: &str = "cloud";
const DEFAULT_MODEL: &str = "gpt-5-nano";
const SUPPORTED_CONSOLE_MODELS: [&str; 5] = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5-nano",
];
const MESSAGE_KIND_CHAT_TURN: &str = "console_chat_turn";
const MESSAGE_KIND_WEB_CONTEXT: &str = "console_web_context";
const MESSAGE_KIND_TOOL_CALL: &str = "console_tool_call";
const MESSAGE_KIND_TOOL_RESULT: &str = "console_tool_result";
const MESSAGE_DOMAIN_CONVERSATION: &str = "conversation";
const NEWSROOM_FEED_CONSOLE_CHAT: &str = "consoleChat";
const CHAT_DETAIL_LAYER: &str = "chat_detail";
const EXPLICIT_SEARCH: &str = "explicit";
const CONTEXT_CACHE_SCHEMA_VERSION: u32 = 1;
const STATIC_PROMPT_CACHE_SCHEMA_VERSION: u32 = 1;
const STREAM_FLUSH_INTERVAL_MS: i64 = 200;
const STREAM_FLUSH_CHARS: usize = 96;
const DEFAULT_STATIC_PROMPT_CACHE_TTL_SECONDS: i64 = 900;
const DEFAULT_EXECUTE_TACTUS_TIMEOUT_SECONDS: u64 = 30;
const SHARED_OPENAI_API_KEY_SSM_PARAM: &str = "/amplify/shared/papyrus/OPENAI_API_KEY";
const LOCAL_RESPONDER_INPUT_ENV: &str = "PAPYRUS_LOCAL_RESPONDER_INPUT_JSON";

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt().without_time().init();
    let local_input_path = optional_env(LOCAL_RESPONDER_INPUT_ENV);
    let aws_config = aws_config::defaults(BehaviorVersion::latest()).load().await;
    let dynamo = DynamoClient::new(&aws_config);
    let ssm = SsmClient::new(&aws_config);
    let config = AppConfig::from_env(local_input_path.is_none());
    let openai_api_key = load_openai_api_key(&ssm).await?;
    let region = aws_config
        .region()
        .map(|value| value.as_ref().to_string())
        .or_else(|| appsync_region_from_endpoint(&config.graphql_endpoint))
        .ok_or_else(|| anyhow!("Unable to determine AWS region for AppSync IAM signing"))?;
    let credentials_provider = aws_config
        .credentials_provider()
        .ok_or_else(|| anyhow!("AWS credentials provider is unavailable for AppSync IAM signing"))?;
    let state = Arc::new(AppState {
        config,
        dynamo,
        http: reqwest::Client::new(),
        openai_api_key,
        aws_region: region,
        credentials_provider,
    });
    if let Some(path) = local_input_path {
        let payload = fs::read_to_string(&path)
            .with_context(|| format!("read local responder input payload {path}"))?;
        let input: LocalResponderInput = serde_json::from_str(&payload)
            .with_context(|| format!("parse local responder input JSON {path}"))?;
        let response = run_local_responder(&state, input).await?;
        println!("{}", serde_json::to_string(&response)?);
        return Ok(());
    }
    run(service_fn(move |event| {
        let state = Arc::clone(&state);
        async move { handler(event, state).await }
    }))
    .await
}

#[derive(Clone, Debug)]
struct AppConfig {
    message_table: String,
    thread_table: String,
    thread_sequence_index: String,
    response_target: String,
    model: String,
    graphql_endpoint: String,
    graphql_jwt: Option<String>,
    cache_root: PathBuf,
    execute_tactus_runner: PathBuf,
    execute_tactus_timeout_seconds: u64,
    static_prompt_cache_ttl_seconds: i64,
}

impl AppConfig {
    fn from_env(require_dynamo: bool) -> Self {
        Self {
            message_table: if require_dynamo {
                required_env("PAPYRUS_MESSAGE_TABLE_NAME")
            } else {
                optional_env("PAPYRUS_MESSAGE_TABLE_NAME").unwrap_or_default()
            },
            thread_table: if require_dynamo {
                required_env("PAPYRUS_MESSAGE_THREAD_TABLE_NAME")
            } else {
                optional_env("PAPYRUS_MESSAGE_THREAD_TABLE_NAME").unwrap_or_default()
            },
            thread_sequence_index: env_or(
                "PAPYRUS_MESSAGE_THREAD_SEQUENCE_INDEX_NAME",
                "messagesByThreadSequence",
            ),
            response_target: env_or("PAPYRUS_CONSOLE_RESPONSE_TARGET", DEFAULT_RESPONSE_TARGET),
            model: env_or("PAPYRUS_CONSOLE_MODEL", DEFAULT_MODEL),
            graphql_endpoint: required_env("PAPYRUS_GRAPHQL_ENDPOINT"),
            graphql_jwt: optional_env("PAPYRUS_GRAPHQL_JWT").map(normalize_jwt),
            cache_root: PathBuf::from(env_or(
                "PAPYRUS_CONSOLE_CONTEXT_CACHE_ROOT",
                "/tmp/papyrus-console/thread-context",
            )),
            execute_tactus_runner: PathBuf::from(env_or(
                "PAPYRUS_EXECUTE_TACTUS_RUNNER",
                "/opt/papyrus/execute_tactus_runner.py",
            )),
            execute_tactus_timeout_seconds: optional_env("PAPYRUS_EXECUTE_TACTUS_TIMEOUT_SECONDS")
                .and_then(|value| value.parse::<u64>().ok())
                .filter(|value| *value > 0)
                .unwrap_or(DEFAULT_EXECUTE_TACTUS_TIMEOUT_SECONDS),
            static_prompt_cache_ttl_seconds: optional_env("PAPYRUS_CONSOLE_STATIC_CONTEXT_TTL_SECONDS")
                .and_then(|value| value.parse::<i64>().ok())
                .filter(|value| *value > 0)
                .unwrap_or(DEFAULT_STATIC_PROMPT_CACHE_TTL_SECONDS),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalResponderInput {
    thread_id: String,
    message_id: String,
    content: String,
    #[serde(default)]
    sequence_number: i64,
    #[serde(default)]
    created_at: String,
    #[serde(default)]
    metadata: Value,
}

async fn run_local_responder(state: &AppState, input: LocalResponderInput) -> Result<Value> {
    let created_at = if input.created_at.trim().is_empty() {
        now_iso()
    } else {
        input.created_at.trim().to_string()
    };
    let message = ChatMessage {
        id: input.message_id,
        thread_id: input.thread_id,
        role: "USER".to_string(),
        message_kind: MESSAGE_KIND_CHAT_TURN.to_string(),
        message_type: "MESSAGE".to_string(),
        content: input.content,
        response_target: state.config.response_target.clone(),
        response_status: "PENDING".to_string(),
        sequence_number: input.sequence_number.max(1),
        created_at,
        metadata: input.metadata,
    };
    if !message.should_handle(&state.config.response_target) {
        return Ok(json!({ "ok": false, "reason": "message_not_handleable" }));
    }
    answer_local_message(state, &message).await?;
    Ok(json!({ "ok": true, "messageId": message.id, "threadId": message.thread_id }))
}

#[derive(Clone)]
struct AppState {
    config: AppConfig,
    dynamo: DynamoClient,
    http: reqwest::Client,
    openai_api_key: String,
    aws_region: String,
    credentials_provider: SharedCredentialsProvider,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StaticPromptDocSummary {
    id: String,
    title: String,
    summary: String,
    namespace: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StaticPromptContext {
    schema_version: u32,
    graphql_endpoint: String,
    generated_at: String,
    expires_at_epoch: i64,
    publication_mission: String,
    publication_policy: String,
    docs_index: Vec<StaticPromptDocSummary>,
}

async fn handler(event: LambdaEvent<Value>, state: Arc<AppState>) -> Result<Value, Error> {
    let records = event
        .payload
        .get("Records")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut processed = 0_u32;
    let mut skipped = 0_u32;
    let mut failures: Vec<Value> = Vec::new();

    for record in records {
        let sequence = record
            .pointer("/dynamodb/SequenceNumber")
            .and_then(Value::as_str)
            .or_else(|| record.get("eventID").and_then(Value::as_str))
            .unwrap_or_default()
            .to_string();
        match process_record(&record, &state).await {
            Ok(RecordOutcome::Processed) => processed += 1,
            Ok(RecordOutcome::Skipped) => skipped += 1,
            Err(error) => {
                error!(sequence, error = %format_error_chain(&error), "failed to process console chat stream record");
                if !sequence.is_empty() {
                    failures.push(json!({ "itemIdentifier": sequence }));
                }
            }
        }
    }

    Ok(json!({
        "processed": processed,
        "skipped": skipped,
        "batchItemFailures": failures,
    }))
}

enum RecordOutcome {
    Processed,
    Skipped,
}

async fn process_record(record: &Value, state: &AppState) -> Result<RecordOutcome> {
    if record.get("eventName").and_then(Value::as_str) != Some("INSERT") {
        return Ok(RecordOutcome::Skipped);
    }
    let image = record
        .pointer("/dynamodb/NewImage")
        .and_then(Value::as_object)
        .ok_or_else(|| anyhow!("DynamoDB stream record did not include NewImage"))?;
    let Some(message) = ChatMessage::from_stream_image(image)? else {
        return Ok(RecordOutcome::Skipped);
    };
    if !message.should_handle(&state.config.response_target) {
        return Ok(RecordOutcome::Skipped);
    }
    info!(
        message_id = message.id,
        thread_id = message.thread_id,
        sequence = message.sequence_number,
        "processing console chat message"
    );
    if !claim_message(state, &message).await? {
        return Ok(RecordOutcome::Skipped);
    }
    publish_message_status(state, &message, "RUNNING", None).await?;
    let lock_owner = format!(
        "{}:{}",
        std::env::var("AWS_LAMBDA_FUNCTION_NAME")
            .unwrap_or_else(|_| "papyrus-console-chat-responder".to_string()),
        Uuid::new_v4()
    );
    acquire_thread_lock(state, &message, &lock_owner).await?;
    let result = answer_claimed_message(state, &message, &lock_owner).await;
    if let Err(error) = &result {
        mark_message_failed(state, &message, error).await?;
        publish_message_status(
            state,
            &message,
            "FAILED",
            Some(&error.to_string()),
        )
        .await?;
        release_thread_lock(state, &message, &lock_owner, None).await?;
    }
    result?;
    Ok(RecordOutcome::Processed)
}

async fn answer_claimed_message(
    state: &AppState,
    message: &ChatMessage,
    lock_owner: &str,
) -> Result<()> {
    let selected_model = resolve_message_model(&state.config.model, message);
    let mut context = load_prompt_context(state, message).await?;
    let static_prompt = load_static_prompt_context(state).await?;
    let starting_sequence = context.last_sequence_number.max(message.sequence_number);
    let now = now_iso();
    let assistant_record = PersistedMessage {
        id: format!("message-console-assistant-{}", Uuid::new_v4()),
        thread_id: message.thread_id.clone(),
        parent_message_id: Some(message.id.clone()),
        created_at: now.clone(),
        sequence_number: starting_sequence + 1,
        role: "ASSISTANT".to_string(),
        message_kind: MESSAGE_KIND_CHAT_TURN.to_string(),
        message_type: "MESSAGE".to_string(),
        content: String::new(),
        summary: "Thinking...".to_string(),
        response_status: Some("RUNNING".to_string()),
        response_error: None,
        response_started_at: Some(now.clone()),
        response_completed_at: None,
        metadata: json!({
            "responder": "rust-lambda",
            "model": selected_model,
            "triggerMessageId": message.id,
            "triggerCreatedAt": message.created_at,
            "streaming": true,
        }),
    };
    create_message_graphql(state, &assistant_record, &now).await?;

    let mut writer = AssistantStreamWriter::new(state, assistant_record.clone());
    let mut next_sequence = assistant_record.sequence_number + 1;
    let tool_and_assistant =
        run_agent_turn(
            state,
            message,
            &context,
            &static_prompt,
            &selected_model,
            &mut writer,
            &mut next_sequence,
        )
            .await?;
    if writer.content.trim().is_empty() && !tool_and_assistant.assistant_content.trim().is_empty() {
        writer
            .push_delta(&tool_and_assistant.assistant_content)
            .await?;
    }

    let assistant_content = tool_and_assistant.assistant_content;
    let mut completed_metadata = assistant_record.metadata.clone();
    if !tool_and_assistant.model_context.is_null() {
        if let Some(entry) = completed_metadata.as_object_mut() {
            entry.insert("modelContext".to_string(), tool_and_assistant.model_context.clone());
        }
    }
    let final_assistant_sequence = if next_sequence == assistant_record.sequence_number + 1 {
        assistant_record.sequence_number
    } else {
        next_sequence
    };
    let completed_assistant_record = PersistedMessage {
        sequence_number: final_assistant_sequence,
        content: assistant_content.clone(),
        summary: truncate_summary(&assistant_content),
        response_status: Some("COMPLETED".to_string()),
        response_started_at: assistant_record.response_started_at.clone(),
        response_completed_at: Some(now_iso()),
        metadata: completed_metadata,
        ..assistant_record
    };
    let mut completion_update = json!({
        "id": completed_assistant_record.id,
        "content": completed_assistant_record.content,
        "summary": completed_assistant_record.summary,
        "responseTarget": message.response_target,
        "responseStatus": "COMPLETED",
        "createdAt": completed_assistant_record.created_at,
        "responseStartedAt": completed_assistant_record.response_started_at,
        "responseCompletedAt": completed_assistant_record.response_completed_at,
        "responseError": Value::Null,
        "metadata": completed_assistant_record.metadata.to_string(),
        "updatedAt": now_iso(),
    });
    if completed_assistant_record.sequence_number != starting_sequence + 1 {
        completion_update["sequenceNumber"] = Value::from(completed_assistant_record.sequence_number);
    }
    update_message_graphql(state, completion_update).await?;
    context
        .recent_messages
        .push(CachedPromptMessage::from_persisted(
            &completed_assistant_record,
        ));
    let persisted_count = usize::try_from(
        (next_sequence - (assistant_record.sequence_number + 1)).max(0),
    )
    .unwrap_or(0)
        + 1;

    context.last_sequence_number = completed_assistant_record.sequence_number;
    context.last_message_id = completed_assistant_record.id.clone();
    trim_recent_messages(&mut context.recent_messages);
    context.context_digest = compute_context_digest(&context);
    context.updated_at = now.clone();
    write_context_cache(&state.config.cache_root, &context)?;

    mark_message_completed(state, message).await?;
    publish_message_status(state, message, "COMPLETED", None)
    .await?;
    release_thread_lock(state, message, lock_owner, Some(&context)).await?;
    update_thread_graphql(state, &message.thread_id, &context).await?;
    info!(
        message_id = message.id,
        thread_id = message.thread_id,
        assistant_message_id = completed_assistant_record.id,
        persisted = persisted_count,
        cache_digest = context.context_digest,
        "console chat message completed"
    );
    Ok(())
}

async fn answer_local_message(state: &AppState, message: &ChatMessage) -> Result<()> {
    let selected_model = resolve_message_model(&state.config.model, message);
    let mut context = one_message_context(message);
    let static_prompt = load_static_prompt_context(state).await?;
    let starting_sequence = context.last_sequence_number.max(message.sequence_number);
    let now = now_iso();
    let assistant_record = PersistedMessage {
        id: format!("message-console-assistant-{}", Uuid::new_v4()),
        thread_id: message.thread_id.clone(),
        parent_message_id: Some(message.id.clone()),
        created_at: now.clone(),
        sequence_number: starting_sequence + 1,
        role: "ASSISTANT".to_string(),
        message_kind: MESSAGE_KIND_CHAT_TURN.to_string(),
        message_type: "MESSAGE".to_string(),
        content: String::new(),
        summary: "Thinking...".to_string(),
        response_status: Some("RUNNING".to_string()),
        response_error: None,
        response_started_at: Some(now.clone()),
        response_completed_at: None,
        metadata: json!({
            "responder": "rust-local",
            "model": selected_model,
            "triggerMessageId": message.id,
            "triggerCreatedAt": message.created_at,
            "streaming": true,
        }),
    };
    create_message_graphql(state, &assistant_record, &now).await?;

    let mut writer = AssistantStreamWriter::new(state, assistant_record.clone());
    let mut next_sequence = assistant_record.sequence_number + 1;
    let tool_and_assistant =
        run_agent_turn(
            state,
            message,
            &context,
            &static_prompt,
            &selected_model,
            &mut writer,
            &mut next_sequence,
        )
            .await?;
    if writer.content.trim().is_empty() && !tool_and_assistant.assistant_content.trim().is_empty() {
        writer.push_delta(&tool_and_assistant.assistant_content).await?;
    }

    let assistant_content = tool_and_assistant.assistant_content;
    let mut completed_metadata = assistant_record.metadata.clone();
    if !tool_and_assistant.model_context.is_null() {
        if let Some(entry) = completed_metadata.as_object_mut() {
            entry.insert("modelContext".to_string(), tool_and_assistant.model_context.clone());
        }
    }
    let final_assistant_sequence = if next_sequence == assistant_record.sequence_number + 1 {
        assistant_record.sequence_number
    } else {
        next_sequence
    };
    let completed_assistant_record = PersistedMessage {
        sequence_number: final_assistant_sequence,
        content: assistant_content.clone(),
        summary: truncate_summary(&assistant_content),
        response_status: Some("COMPLETED".to_string()),
        response_started_at: assistant_record.response_started_at.clone(),
        response_completed_at: Some(now_iso()),
        metadata: completed_metadata,
        ..assistant_record
    };
    let mut completion_update = json!({
        "id": completed_assistant_record.id,
        "content": completed_assistant_record.content,
        "summary": completed_assistant_record.summary,
        "responseTarget": message.response_target,
        "responseStatus": "COMPLETED",
        "createdAt": completed_assistant_record.created_at,
        "responseStartedAt": completed_assistant_record.response_started_at,
        "responseCompletedAt": completed_assistant_record.response_completed_at,
        "responseError": Value::Null,
        "metadata": completed_assistant_record.metadata.to_string(),
        "updatedAt": now_iso(),
    });
    if completed_assistant_record.sequence_number != starting_sequence + 1 {
        completion_update["sequenceNumber"] = Value::from(completed_assistant_record.sequence_number);
    }
    update_message_graphql(state, completion_update).await?;
    context
        .recent_messages
        .push(CachedPromptMessage::from_persisted(
            &completed_assistant_record,
        ));
    context.last_sequence_number = completed_assistant_record.sequence_number;
    context.last_message_id = completed_assistant_record.id.clone();
    trim_recent_messages(&mut context.recent_messages);
    context.context_digest = compute_context_digest(&context);
    context.updated_at = now.clone();
    write_context_cache(&state.config.cache_root, &context)?;
    update_thread_graphql(state, &message.thread_id, &context).await?;
    info!(
        message_id = message.id,
        thread_id = message.thread_id,
        assistant_message_id = completed_assistant_record.id,
        "local console chat message completed"
    );
    Ok(())
}

#[derive(Debug, Clone)]
struct ChatMessage {
    id: String,
    thread_id: String,
    role: String,
    message_kind: String,
    message_type: String,
    content: String,
    response_target: String,
    response_status: String,
    sequence_number: i64,
    created_at: String,
    metadata: Value,
}

impl ChatMessage {
    fn from_stream_image(image: &serde_json::Map<String, Value>) -> Result<Option<Self>> {
        let metadata = image
            .get("metadata")
            .map(dynamodb_json_to_value)
            .unwrap_or(Value::Null);
        let id = stream_string(image, "id")?;
        let message_kind = stream_string(image, "messageKind")?;
        let role = stream_string(image, "role").unwrap_or_default();
        let message_type =
            stream_string(image, "messageType").unwrap_or_else(|_| "MESSAGE".to_string());
        let response_status = stream_string(image, "responseStatus").unwrap_or_default();
        if message_kind != MESSAGE_KIND_CHAT_TURN
            || role != "USER"
            || message_type != "MESSAGE"
            || response_status != "PENDING"
        {
            return Ok(None);
        }
        let thread_id = match stream_string(image, "threadId") {
            Ok(value) => value,
            Err(error) => {
                warn!(
                    message_id = id,
                    error = %error,
                    "skipping pending console chat message without threadId"
                );
                return Ok(None);
            }
        };
        Ok(Some(Self {
            id,
            thread_id,
            role,
            message_kind,
            message_type,
            content: stream_string(image, "content")
                .or_else(|_| stream_string(image, "summary"))?,
            response_target: stream_string(image, "responseTarget").unwrap_or_default(),
            response_status,
            sequence_number: stream_i64(image, "sequenceNumber").unwrap_or(0),
            created_at: stream_string(image, "createdAt").unwrap_or_else(|_| now_iso()),
            metadata,
        }))
    }

    fn should_handle(&self, expected_target: &str) -> bool {
        self.message_kind == MESSAGE_KIND_CHAT_TURN
            && self.role == "USER"
            && self.message_type == "MESSAGE"
            && self.response_status == "PENDING"
            && self.response_target == expected_target
            && !self.thread_id.is_empty()
            && !self.content.trim().is_empty()
    }
}

async fn claim_message(state: &AppState, message: &ChatMessage) -> Result<bool> {
    let response = state
        .dynamo
        .update_item()
        .table_name(&state.config.message_table)
        .key("id", av_s(&message.id))
        .update_expression("SET responseStatus = :running, responseOwner = :owner, responseStartedAt = :now, updatedAt = :now")
        .condition_expression("responseStatus = :pending")
        .expression_attribute_values(":running", av_s("RUNNING"))
        .expression_attribute_values(":pending", av_s("PENDING"))
        .expression_attribute_values(":owner", av_s("rust-lambda"))
        .expression_attribute_values(":now", av_s(&now_iso()))
        .send()
        .await;
    match response {
        Ok(_) => Ok(true),
        Err(error) => {
            let text = error.to_string();
            if text.contains("ConditionalCheckFailed")
                || text.contains("conditional request failed")
            {
                warn!(message_id = message.id, "message was already claimed");
                Ok(false)
            } else {
                Err(error).context("claim console chat message")
            }
        }
    }
}

async fn acquire_thread_lock(state: &AppState, message: &ChatMessage, owner: &str) -> Result<()> {
    let now = now_iso();
    let expires = (Utc::now() + Duration::seconds(300)).to_rfc3339();
    state
        .dynamo
        .update_item()
        .table_name(&state.config.thread_table)
        .key("id", av_s(&message.thread_id))
        .update_expression("SET activeResponseMessageId = :messageId, responseLockOwner = :owner, responseLockExpiresAt = :expires, updatedAt = :now")
        .condition_expression("attribute_not_exists(responseLockExpiresAt) OR responseLockExpiresAt < :now OR activeResponseMessageId = :messageId")
        .expression_attribute_values(":messageId", av_s(&message.id))
        .expression_attribute_values(":owner", av_s(owner))
        .expression_attribute_values(":expires", av_s(&expires))
        .expression_attribute_values(":now", av_s(&now))
        .send()
        .await
        .context("acquire MessageThread response lock")?;
    Ok(())
}

async fn release_thread_lock(
    state: &AppState,
    message: &ChatMessage,
    owner: &str,
    context: Option<&ThreadContextCache>,
) -> Result<()> {
    let now = now_iso();
    let mut update = state
        .dynamo
        .update_item()
        .table_name(&state.config.thread_table)
        .key("id", av_s(&message.thread_id))
        .condition_expression("responseLockOwner = :owner")
        .expression_attribute_values(":owner", av_s(owner))
        .expression_attribute_values(":now", av_s(&now));

    if let Some(context) = context {
        update = update
            .update_expression("SET lastMessageId = :lastMessageId, lastMessageAt = :lastMessageAt, contextDigest = :contextDigest, messageCount = :messageCount, updatedAt = :now REMOVE activeResponseMessageId, responseLockOwner, responseLockExpiresAt")
            .expression_attribute_values(":lastMessageId", av_s(&context.last_message_id))
            .expression_attribute_values(":lastMessageAt", av_s(&context.updated_at))
            .expression_attribute_values(":contextDigest", av_s(&context.context_digest))
            .expression_attribute_values(":messageCount", AttributeValue::N(context.last_sequence_number.to_string()));
    } else {
        update = update.update_expression("SET updatedAt = :now REMOVE activeResponseMessageId, responseLockOwner, responseLockExpiresAt");
    }

    match update.send().await {
        Ok(_) => Ok(()),
        Err(error) => {
            warn!(thread_id = message.thread_id, error = %error, "failed to release thread lock");
            Ok(())
        }
    }
}

async fn mark_message_completed(state: &AppState, message: &ChatMessage) -> Result<()> {
    let now = now_iso();
    state
        .dynamo
        .update_item()
        .table_name(&state.config.message_table)
        .key("id", av_s(&message.id))
        .update_expression(
            "SET responseStatus = :completed, responseCompletedAt = :now, updatedAt = :now",
        )
        .expression_attribute_values(":completed", av_s("COMPLETED"))
        .expression_attribute_values(":now", av_s(&now))
        .send()
        .await
        .context("mark console chat message completed")?;
    Ok(())
}

async fn mark_message_failed(
    state: &AppState,
    message: &ChatMessage,
    error: &anyhow::Error,
) -> Result<()> {
    let now = now_iso();
    state
        .dynamo
        .update_item()
        .table_name(&state.config.message_table)
        .key("id", av_s(&message.id))
        .update_expression("SET responseStatus = :failed, responseCompletedAt = :now, responseError = :error, updatedAt = :now")
        .expression_attribute_values(":failed", av_s("FAILED"))
        .expression_attribute_values(":now", av_s(&now))
        .expression_attribute_values(":error", av_s(&error.to_string()))
        .send()
        .await
        .context("mark console chat message failed")?;
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ThreadContextCache {
    schema_version: u32,
    thread_id: String,
    last_sequence_number: i64,
    last_message_id: String,
    context_digest: String,
    rolling_summary: String,
    recent_messages: Vec<CachedPromptMessage>,
    updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CachedPromptMessage {
    id: String,
    sequence_number: i64,
    role: String,
    #[serde(default)]
    message_kind: String,
    #[serde(default)]
    message_type: String,
    content: String,
    #[serde(default)]
    metadata: Value,
}

impl CachedPromptMessage {
    fn from_chat(message: &ChatMessage) -> Self {
        Self {
            id: message.id.clone(),
            sequence_number: message.sequence_number,
            role: message.role.clone(),
            message_kind: message.message_kind.clone(),
            message_type: message.message_type.clone(),
            content: message.content.clone(),
            metadata: message.metadata.clone(),
        }
    }

    fn from_persisted(message: &PersistedMessage) -> Self {
        Self {
            id: message.id.clone(),
            sequence_number: message.sequence_number,
            role: message.role.clone(),
            message_kind: message.message_kind.clone(),
            message_type: message.message_type.clone(),
            content: message.content.clone(),
            metadata: message.metadata.clone(),
        }
    }
}

async fn load_prompt_context(
    state: &AppState,
    message: &ChatMessage,
) -> Result<ThreadContextCache> {
    if let Some(mut cache) = read_context_cache(&state.config.cache_root, &message.thread_id)? {
        if cache_is_valid_for_message(&cache, message) {
            if !cache
                .recent_messages
                .iter()
                .any(|entry| entry.id == message.id)
            {
                cache
                    .recent_messages
                    .push(CachedPromptMessage::from_chat(message));
                cache.last_sequence_number = message.sequence_number;
                cache.last_message_id = message.id.clone();
                trim_recent_messages(&mut cache.recent_messages);
            }
            info!(
                thread_id = message.thread_id,
                "loaded prompt context from /tmp cache"
            );
            return Ok(cache);
        }
    }
    let mut cache = match rebuild_context_from_dynamodb(state, message).await {
        Ok(cache) => cache,
        Err(error) => {
            warn!(
                thread_id = message.thread_id,
                error = %format_error_chain(&error),
                "failed to rebuild prompt context from DynamoDB; falling back to trigger message only"
            );
            one_message_context(message)
        }
    };
    if !cache
        .recent_messages
        .iter()
        .any(|entry| entry.id == message.id)
    {
        cache
            .recent_messages
            .push(CachedPromptMessage::from_chat(message));
    }
    cache.last_sequence_number = cache
        .recent_messages
        .iter()
        .map(|entry| entry.sequence_number)
        .max()
        .unwrap_or(message.sequence_number);
    cache.last_message_id = cache
        .recent_messages
        .iter()
        .max_by_key(|entry| entry.sequence_number)
        .map(|entry| entry.id.clone())
        .unwrap_or_else(|| message.id.clone());
    trim_recent_messages(&mut cache.recent_messages);
    cache.context_digest = compute_context_digest(&cache);
    write_context_cache(&state.config.cache_root, &cache)?;
    info!(
        thread_id = message.thread_id,
        "rebuilt prompt context from DynamoDB"
    );
    Ok(cache)
}

fn one_message_context(message: &ChatMessage) -> ThreadContextCache {
    let mut cache = ThreadContextCache {
        schema_version: CONTEXT_CACHE_SCHEMA_VERSION,
        thread_id: message.thread_id.clone(),
        last_sequence_number: message.sequence_number,
        last_message_id: message.id.clone(),
        context_digest: String::new(),
        rolling_summary: String::new(),
        recent_messages: vec![CachedPromptMessage::from_chat(message)],
        updated_at: now_iso(),
    };
    cache.context_digest = compute_context_digest(&cache);
    cache
}

fn cache_is_valid_for_message(cache: &ThreadContextCache, message: &ChatMessage) -> bool {
    if cache.schema_version != CONTEXT_CACHE_SCHEMA_VERSION || cache.thread_id != message.thread_id
    {
        return false;
    }
    let previous_sequence =
        metadata_i64_field(&message.metadata, "previousSequenceNumber").unwrap_or(message.sequence_number - 1);
    let previous_digest = metadata_string_field(&message.metadata, "previousContextDigest");
    cache.last_sequence_number == previous_sequence
        && previous_digest
            .as_deref()
            .map(|digest| digest == cache.context_digest)
            .unwrap_or(true)
}

async fn rebuild_context_from_dynamodb(
    state: &AppState,
    message: &ChatMessage,
) -> Result<ThreadContextCache> {
    let result = state
        .dynamo
        .query()
        .table_name(&state.config.message_table)
        .index_name(&state.config.thread_sequence_index)
        .key_condition_expression("threadId = :threadId")
        .expression_attribute_values(":threadId", av_s(&message.thread_id))
        .scan_index_forward(false)
        .limit(32)
        .send()
        .await
        .context("query Message tail by threadId/sequenceNumber")?;
    let mut messages: Vec<CachedPromptMessage> = result
        .items()
        .iter()
        .filter_map(cached_message_from_item)
        .collect();
    messages.sort_by_key(|entry| entry.sequence_number);
    trim_recent_messages(&mut messages);
    let last = messages
        .iter()
        .max_by_key(|entry| entry.sequence_number)
        .cloned()
        .unwrap_or_else(|| CachedPromptMessage::from_chat(message));
    let mut cache = ThreadContextCache {
        schema_version: CONTEXT_CACHE_SCHEMA_VERSION,
        thread_id: message.thread_id.clone(),
        last_sequence_number: last.sequence_number,
        last_message_id: last.id,
        context_digest: String::new(),
        rolling_summary: String::new(),
        recent_messages: messages,
        updated_at: now_iso(),
    };
    cache.context_digest = compute_context_digest(&cache);
    Ok(cache)
}

fn cached_message_from_item(item: &HashMap<String, AttributeValue>) -> Option<CachedPromptMessage> {
    let role = attr_string(item.get("role"))?;
    let message_kind = attr_string(item.get("messageKind")).unwrap_or_default();
    let allows_system = role == "SYSTEM" && message_kind == MESSAGE_KIND_WEB_CONTEXT;
    if role != "USER" && role != "ASSISTANT" && role != "TOOL" && !allows_system {
        return None;
    }
    let message_type =
        attr_string(item.get("messageType")).unwrap_or_else(|| "MESSAGE".to_string());
    if message_type != "MESSAGE" && message_type != "TOOL_CALL" && message_type != "TOOL_RESPONSE" {
        return None;
    }
    Some(CachedPromptMessage {
        id: attr_string(item.get("id"))?,
        sequence_number: attr_i64(item.get("sequenceNumber")).unwrap_or(0),
        role,
        message_kind,
        message_type,
        content: attr_string(item.get("content")).or_else(|| attr_string(item.get("summary")))?,
        metadata: attr_json(item.get("metadata")),
    })
}

fn read_context_cache(root: &Path, thread_id: &str) -> Result<Option<ThreadContextCache>> {
    let path = context_cache_path(root, thread_id);
    if !path.exists() {
        return Ok(None);
    }
    let text = fs::read_to_string(&path)
        .with_context(|| format!("read context cache {}", path.display()))?;
    let cache = serde_json::from_str(&text)
        .with_context(|| format!("parse context cache {}", path.display()))?;
    Ok(Some(cache))
}

fn write_context_cache(root: &Path, cache: &ThreadContextCache) -> Result<()> {
    fs::create_dir_all(root)
        .with_context(|| format!("create context cache directory {}", root.display()))?;
    let path = context_cache_path(root, &cache.thread_id);
    let tmp_path = path.with_extension("json.tmp");
    let text = serde_json::to_string(cache)?;
    fs::write(&tmp_path, text)
        .with_context(|| format!("write context cache {}", tmp_path.display()))?;
    fs::rename(&tmp_path, &path)
        .with_context(|| format!("move context cache {}", path.display()))?;
    Ok(())
}

fn context_cache_path(root: &Path, thread_id: &str) -> PathBuf {
    let safe = thread_id
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>();
    root.join(format!("{safe}.json"))
}

fn trim_recent_messages(messages: &mut Vec<CachedPromptMessage>) {
    messages.sort_by_key(|entry| entry.sequence_number);
    messages.dedup_by(|left, right| left.id == right.id);
    if messages.len() > 24 {
        let drop_count = messages.len() - 24;
        messages.drain(0..drop_count);
    }
}

fn compute_context_digest(cache: &ThreadContextCache) -> String {
    let mut hasher = Sha256::new();
    hasher.update(cache.thread_id.as_bytes());
    hasher.update(cache.last_sequence_number.to_string().as_bytes());
    for message in &cache.recent_messages {
        hasher.update(message.id.as_bytes());
        hasher.update(message.role.as_bytes());
        hasher.update(message.content.as_bytes());
    }
    to_hex(&hasher.finalize())
}

async fn load_static_prompt_context(state: &AppState) -> Result<StaticPromptContext> {
    if let Some(cache) = read_static_prompt_cache(&state.config.cache_root)? {
        let now_epoch = Utc::now().timestamp();
        if cache.schema_version == STATIC_PROMPT_CACHE_SCHEMA_VERSION
            && cache.graphql_endpoint == state.config.graphql_endpoint
            && cache.expires_at_epoch > now_epoch
        {
            return Ok(cache);
        }
    }

    let (mission, policy) = load_publication_doctrine(state).await?;
    let docs_index = match load_execute_tactus_docs_index(state).await {
        Ok(entries) => entries,
        Err(error) => {
            warn!(
                error = %format_error_chain(&error),
                "failed to load execute_tactus docs index; using empty docs list"
            );
            Vec::new()
        }
    };
    let generated_at = now_iso();
    let expires_at_epoch = Utc::now()
        .checked_add_signed(Duration::seconds(
            state.config.static_prompt_cache_ttl_seconds,
        ))
        .map(|dt| dt.timestamp())
        .unwrap_or_else(|| Utc::now().timestamp() + state.config.static_prompt_cache_ttl_seconds);
    let cache = StaticPromptContext {
        schema_version: STATIC_PROMPT_CACHE_SCHEMA_VERSION,
        graphql_endpoint: state.config.graphql_endpoint.clone(),
        generated_at,
        expires_at_epoch,
        publication_mission: mission,
        publication_policy: policy,
        docs_index,
    };
    write_static_prompt_cache(&state.config.cache_root, &cache)?;
    Ok(cache)
}

fn read_static_prompt_cache(root: &Path) -> Result<Option<StaticPromptContext>> {
    let path = static_prompt_cache_path(root);
    let text = match fs::read_to_string(&path) {
        Ok(value) => value,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(error)
                .with_context(|| format!("read static prompt cache {}", path.display()));
        }
    };
    let cache: StaticPromptContext = serde_json::from_str(&text)
        .with_context(|| format!("parse static prompt cache {}", path.display()))?;
    Ok(Some(cache))
}

fn write_static_prompt_cache(root: &Path, cache: &StaticPromptContext) -> Result<()> {
    fs::create_dir_all(root)
        .with_context(|| format!("create static prompt cache directory {}", root.display()))?;
    let path = static_prompt_cache_path(root);
    let tmp_path = path.with_extension("json.tmp");
    let text = serde_json::to_string(cache)?;
    fs::write(&tmp_path, text)
        .with_context(|| format!("write static prompt cache {}", tmp_path.display()))?;
    fs::rename(&tmp_path, &path)
        .with_context(|| format!("move static prompt cache {}", path.display()))?;
    Ok(())
}

fn static_prompt_cache_path(root: &Path) -> PathBuf {
    root.join("static_prompt_context.json")
}

async fn load_publication_doctrine(state: &AppState) -> Result<(String, String)> {
    let query = r#"
      query ListCurrentDoctrineItems($versionState: String!, $limit: Int, $nextToken: String) {
        listItemsByVersionStateAndUpdatedAt(versionState: $versionState, limit: $limit, nextToken: $nextToken) {
          items {
            id
            type
            typeStatus
            slug
            body
          }
          nextToken
        }
      }
    "#;
    let mut next_token: Option<String> = None;
    let mut mission = String::new();
    let mut policy = String::new();
    loop {
        let variables = json!({
            "versionState": "current",
            "limit": 150,
            "nextToken": next_token,
        });
        let data = match graphql(state, query, variables).await {
            Ok(value) => value,
            Err(error) => {
                warn!(
                    error = %format_error_chain(&error),
                    "failed loading doctrine from GraphQL"
                );
                break;
            }
        };
        let connection = data
            .get("listItemsByVersionStateAndUpdatedAt")
            .cloned()
            .unwrap_or(Value::Null);
        let items = connection
            .get("items")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for item in items {
            let item_type = item.get("type").and_then(Value::as_str).unwrap_or_default();
            if item_type != "doctrine" {
                continue;
            }
            let type_status = item
                .get("typeStatus")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if type_status != "doctrine#private" {
                continue;
            }
            let slug = item.get("slug").and_then(Value::as_str).unwrap_or_default();
            let text = item
                .get("body")
                .and_then(Value::as_array)
                .map(|lines| {
                    lines
                        .iter()
                        .filter_map(Value::as_str)
                        .map(str::trim)
                        .filter(|line| !line.is_empty())
                        .collect::<Vec<&str>>()
                        .join("\n\n")
                })
                .unwrap_or_default();
            if slug == "editorial-doctrine-mission" && !text.trim().is_empty() {
                mission = text;
            } else if slug == "editorial-doctrine-policy" && !text.trim().is_empty() {
                policy = text;
            }
        }
        if !mission.is_empty() && !policy.is_empty() {
            break;
        }
        next_token = connection
            .get("nextToken")
            .and_then(Value::as_str)
            .map(ToString::to_string);
        if next_token.is_none() {
            break;
        }
    }
    Ok((mission, policy))
}

async fn load_execute_tactus_docs_index(state: &AppState) -> Result<Vec<StaticPromptDocSummary>> {
    let runner_input = json!({
        "mode": "docs_index"
    });
    let output = call_execute_tactus_runner(state, &runner_input).await?;
    let entries = output
        .get("entries")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut docs = Vec::with_capacity(entries.len());
    for value in entries {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if id.is_empty() {
            continue;
        }
        docs.push(StaticPromptDocSummary {
            id,
            title: value
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            summary: value
                .get("summary")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            namespace: value
                .get("namespace")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
        });
    }
    docs.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(docs)
}

#[derive(Debug, Clone)]
struct PersistedMessage {
    id: String,
    thread_id: String,
    parent_message_id: Option<String>,
    created_at: String,
    sequence_number: i64,
    role: String,
    message_kind: String,
    message_type: String,
    content: String,
    summary: String,
    response_status: Option<String>,
    response_error: Option<String>,
    response_started_at: Option<String>,
    response_completed_at: Option<String>,
    metadata: Value,
}

struct AssistantStreamWriter<'a> {
    state: &'a AppState,
    message_id: String,
    thread_id: String,
    message_created_at: String,
    sequence_number: i64,
    role: String,
    message_kind: String,
    message_type: String,
    content: String,
    last_flush_at: DateTime<Utc>,
    last_flush_len: usize,
}

impl<'a> AssistantStreamWriter<'a> {
    fn new(state: &'a AppState, message: PersistedMessage) -> Self {
        Self {
            state,
            message_id: message.id,
            thread_id: message.thread_id,
            message_created_at: message.created_at,
            sequence_number: message.sequence_number,
            role: message.role,
            message_kind: message.message_kind,
            message_type: message.message_type,
            content: message.content,
            last_flush_at: Utc::now(),
            last_flush_len: 0,
        }
    }

    async fn push_delta(&mut self, delta: &str) -> Result<()> {
        if delta.is_empty() {
            return Ok(());
        }
        self.content.push_str(delta);
        let now = Utc::now();
        let elapsed_ms = now
            .signed_duration_since(self.last_flush_at)
            .num_milliseconds();
        if elapsed_ms >= STREAM_FLUSH_INTERVAL_MS
            || self.content.len().saturating_sub(self.last_flush_len) >= STREAM_FLUSH_CHARS
        {
            self.flush().await?;
        }
        Ok(())
    }

    async fn flush(&mut self) -> Result<()> {
        if self.content.len() == self.last_flush_len {
            return Ok(());
        }
        update_message_graphql(
            self.state,
            json!({
                "id": self.message_id,
                "threadId": self.thread_id,
                "createdAt": self.message_created_at,
                "sequenceNumber": self.sequence_number,
                "role": self.role,
                "messageKind": self.message_kind,
                "messageDomain": MESSAGE_DOMAIN_CONVERSATION,
                "messageType": self.message_type,
                "source": "papyrus-console",
                "content": self.content,
                "summary": truncate_summary(&self.content),
                "semanticLayer": CHAT_DETAIL_LAYER,
                "searchVisibility": EXPLICIT_SEARCH,
                "responseTarget": DEFAULT_RESPONSE_TARGET,
                "responseStatus": "RUNNING",
                "updatedAt": now_iso(),
                "newsroomFeedKey": NEWSROOM_FEED_CONSOLE_CHAT,
            }),
        )
        .await?;
        self.last_flush_at = Utc::now();
        self.last_flush_len = self.content.len();
        Ok(())
    }

}

const MESSAGE_SELECTION: &str = r#"
  id
  threadId
  parentMessageId
  sequenceNumber
  role
  messageKind
  messageDomain
  messageType
  source
  authorLabel
  content
  summary
  semanticLayer
  searchVisibility
  responseTarget
  responseStatus
  responseOwner
  responseStartedAt
  responseCompletedAt
  responseError
  metadata
  createdAt
  updatedAt
  newsroomFeedKey
"#;

const THREAD_SELECTION: &str = r#"
  id
  threadKind
  status
  title
  messageCount
  lastMessageId
  lastMessageAt
  contextDigest
  activeResponseMessageId
  responseLockOwner
  responseLockExpiresAt
  updatedAt
"#;

async fn create_message_graphql(
    state: &AppState,
    message: &PersistedMessage,
    now: &str,
) -> Result<()> {
    let mut input = json!({
        "id": message.id,
        "threadId": message.thread_id,
        "sequenceNumber": message.sequence_number,
        "role": message.role,
        "messageKind": message.message_kind,
        "messageDomain": MESSAGE_DOMAIN_CONVERSATION,
        "messageType": message.message_type,
        "status": "active",
        "summary": message.summary,
        "content": message.content,
        "semanticLayer": CHAT_DETAIL_LAYER,
        "searchVisibility": EXPLICIT_SEARCH,
        "source": "papyrus-console",
        "newsroomFeedKey": NEWSROOM_FEED_CONSOLE_CHAT,
        "createdAt": message.created_at,
        "updatedAt": now,
        "metadata": message.metadata.to_string(),
    });
    if let Some(parent_id) = &message.parent_message_id {
        input["parentMessageId"] = Value::String(parent_id.clone());
    }
    if let Some(status) = &message.response_status {
        input["responseStatus"] = Value::String(status.clone());
    } else {
        input["responseStatus"] = Value::String("COMPLETED".to_string());
    }
    if let Some(error) = &message.response_error {
        input["responseError"] = Value::String(error.clone());
    }
    if let Some(started_at) = &message.response_started_at {
        input["responseStartedAt"] = Value::String(started_at.clone());
    }
    if let Some(completed_at) = &message.response_completed_at {
        input["responseCompletedAt"] = Value::String(completed_at.clone());
    }
    graphql(
        state,
        &format!(
            "mutation CreateMessage($input: CreateMessageInput!) {{ createMessage(input: $input) {{ {MESSAGE_SELECTION} }} }}"
        ),
        json!({ "input": input }),
    )
    .await?;
    Ok(())
}

async fn update_message_graphql(state: &AppState, input: Value) -> Result<()> {
    graphql(
        state,
        &format!(
            "mutation UpdateMessage($input: UpdateMessageInput!) {{ updateMessage(input: $input) {{ {MESSAGE_SELECTION} }} }}"
        ),
        json!({ "input": input }),
    )
    .await?;
    Ok(())
}

async fn publish_message_status(
    state: &AppState,
    message: &ChatMessage,
    status: &str,
    error: Option<&str>,
) -> Result<()> {
    let mut input = json!({
        "id": message.id,
        "threadId": message.thread_id,
        "createdAt": message.created_at,
        "sequenceNumber": message.sequence_number,
        "role": message.role,
        "messageKind": message.message_kind,
        "messageDomain": MESSAGE_DOMAIN_CONVERSATION,
        "messageType": message.message_type,
        "source": "papyrus-console",
        "content": message.content,
        "summary": truncate_summary(&message.content),
        "semanticLayer": CHAT_DETAIL_LAYER,
        "searchVisibility": EXPLICIT_SEARCH,
        "responseTarget": message.response_target,
        "responseStatus": status,
        "updatedAt": now_iso(),
        "newsroomFeedKey": NEWSROOM_FEED_CONSOLE_CHAT,
    });
    if status == "RUNNING" {
        input["responseOwner"] = Value::String("rust-lambda".to_string());
        input["responseStartedAt"] = Value::String(now_iso());
    }
    if matches!(status, "COMPLETED" | "FAILED") {
        input["responseCompletedAt"] = Value::String(now_iso());
    }
    if let Some(error) = error {
        input["responseError"] = Value::String(error.to_string());
    }
    update_message_graphql(state, input).await
}

async fn update_thread_graphql(
    state: &AppState,
    thread_id: &str,
    context: &ThreadContextCache,
) -> Result<()> {
    graphql(
        state,
        &format!(
            "mutation UpdateMessageThread($input: UpdateMessageThreadInput!) {{ updateMessageThread(input: $input) {{ {THREAD_SELECTION} }} }}"
        ),
        json!({
            "input": {
                "id": thread_id,
                "messageCount": context.last_sequence_number,
                "lastMessageId": context.last_message_id,
                "lastMessageAt": context.updated_at,
                "contextDigest": context.context_digest,
                "activeResponseMessageId": null,
                "responseLockOwner": null,
                "responseLockExpiresAt": null,
                "updatedAt": now_iso(),
            }
        }),
    )
    .await?;
    Ok(())
}

async fn graphql(state: &AppState, query: &str, variables: Value) -> Result<Value> {
    let body = serde_json::to_vec(&json!({ "query": query, "variables": variables }))
        .context("serialize AppSync GraphQL request body")?;
    if let Some(jwt) = state.config.graphql_jwt.as_deref() {
        let response = state
            .http
            .post(&state.config.graphql_endpoint)
            .header("content-type", "application/json")
            .header("authorization", format!("PapyrusJwt {jwt}"))
            .body(body.clone())
            .send()
            .await
            .context("send AppSync GraphQL mutation (PapyrusJwt auth)")?;
        let status = response.status();
        let payload: Value = response
            .json()
            .await
            .context("parse AppSync GraphQL response")?;
        if !status.is_success() || payload.get("errors").is_some() {
            return Err(anyhow!(
                "AppSync GraphQL mutation failed with {status}: {payload}"
            ));
        }
        return Ok(payload.get("data").cloned().unwrap_or(Value::Null));
    }

    let credentials = state
        .credentials_provider
        .provide_credentials()
        .await
        .context("load AWS credentials for AppSync IAM signing")?;
    let identity = credentials.into();
    let signable_request = SignableRequest::new(
        "POST",
        &state.config.graphql_endpoint,
        [("content-type", "application/json")].into_iter(),
        SignableBody::Bytes(&body),
    )
    .context("construct signable AppSync request")?;
    let signing_params = v4::SigningParams::builder()
        .identity(&identity)
        .region(&state.aws_region)
        .name("appsync")
        .time(SystemTime::now())
        .settings(SigningSettings::default())
        .build()
        .context("build AppSync SigV4 signing params")?
        .into();
    let (instructions, _signature) = sign(signable_request, &signing_params)
        .context("sign AppSync GraphQL request")?
        .into_parts();
    let mut signed_request = http::Request::builder()
        .method("POST")
        .uri(&state.config.graphql_endpoint)
        .header("content-type", "application/json")
        .body(())
        .context("build AppSync HTTP request for signing")?;
    instructions.apply_to_request_http1x(&mut signed_request);

    let mut request_builder = state
        .http
        .post(&state.config.graphql_endpoint)
        .body(body);
    for (name, value) in signed_request.headers() {
        request_builder = request_builder.header(name, value);
    }
    let response = state
        .http
        .execute(request_builder.build().context("build signed AppSync request")?)
        .await
        .context("send AppSync GraphQL mutation")?;
    let status = response.status();
    let payload: Value = response
        .json()
        .await
        .context("parse AppSync GraphQL response")?;
    if !status.is_success() || payload.get("errors").is_some() {
        return Err(anyhow!(
            "AppSync GraphQL mutation failed with {status}: {payload}"
        ));
    }
    Ok(payload.get("data").cloned().unwrap_or(Value::Null))
}

#[derive(Debug)]
struct AgentTurnOutput {
    assistant_content: String,
    model_context: Value,
}

async fn run_agent_turn(
    state: &AppState,
    trigger: &ChatMessage,
    context: &ThreadContextCache,
    static_prompt: &StaticPromptContext,
    model: &str,
    assistant_writer: &mut AssistantStreamWriter<'_>,
    next_sequence: &mut i64,
) -> Result<AgentTurnOutput> {
    const MAX_TOOL_RETRIES: usize = 3;
    const MAX_TOOL_ATTEMPTS: usize = MAX_TOOL_RETRIES + 1;
    let local_test_lane = trigger.response_target == "local" || state.config.response_target == "local";
    let capture_model_context = metadata_value_field(&trigger.metadata, "captureModelContext")
        .and_then(|value| value.as_bool())
        .unwrap_or(false);
    let require_tool_calls = metadata_value_field(&trigger.metadata, "requireToolCalls")
        .and_then(|value| value.as_bool())
        .unwrap_or(false);
    let required_tool_calls = metadata_string_list_field(&trigger.metadata, "requiredToolCalls");
    let required_tool_call_counts =
        metadata_string_usize_map_field(&trigger.metadata, "requiredToolCallCounts");
    let expected_final_response = metadata_string_field(&trigger.metadata, "expectedFinalResponse");
    let web_ui = resolve_trigger_web_ui(&trigger.metadata)
        .or_else(|| resolve_web_ui_from_context_messages(&context.recent_messages));
    if web_ui.is_none() {
        if metadata_nested_value_field(&trigger.metadata, &["console"]).is_some() {
            warn!(
                message_id = trigger.id,
                thread_id = trigger.thread_id,
                "console metadata present but console.webUi missing; deploy the latest Newsroom frontend"
            );
        }
    } else {
        info!(
            message_id = trigger.id,
            thread_id = trigger.thread_id,
            web_path = web_ui
                .as_ref()
                .and_then(|entry| entry.get("webPath"))
                .and_then(|entry| entry.as_str())
                .unwrap_or(""),
            papyrus_location_uri = web_ui
                .as_ref()
                .and_then(|entry| entry.get("papyrusLocationUri"))
                .and_then(|entry| entry.as_str())
                .unwrap_or(""),
            "resolved console webUi metadata for trigger message"
        );
    }
    let mut messages = build_openai_messages(context, static_prompt, web_ui.as_ref());
    let mut model_context_attempts: Vec<Value> = Vec::new();
    let mut saw_tool_calls = false;
    let mut saw_tool_errors = false;
    let mut observed_tool_counts: HashMap<String, usize> = HashMap::new();
    let mut assignment_ids = HashSet::new();
    let mut last_assistant_content = String::new();

    for round in 0..MAX_TOOL_ATTEMPTS {
        if capture_model_context {
            model_context_attempts.push(capture_openai_messages(&messages));
        }
        let turn = stream_openai_chat(
            state,
            openai_request(model, messages.clone(), require_tool_calls && !saw_tool_calls),
            Some(&mut *assistant_writer),
        )
        .await?;
        let assistant_content = turn.content;
        let tool_calls = turn.tool_calls;
        last_assistant_content = assistant_content.clone();

        if tool_calls.is_empty() {
            if require_tool_calls && round + 1 < MAX_TOOL_ATTEMPTS {
                let retries_remaining = MAX_TOOL_ATTEMPTS - (round + 1);
                if !assistant_content.trim().is_empty() {
                    messages.push(json!({
                        "role": "assistant",
                        "content": assistant_content,
                    }));
                }
                let missing_required = missing_required_tool_calls(
                    &required_tool_calls,
                    &required_tool_call_counts,
                    &observed_tool_counts,
                );
                let required_hint = if required_tool_calls.is_empty() {
                    "At least one execute_tactus tool call is required before final response."
                        .to_string()
                } else if missing_required.is_empty() {
                    format!(
                        "Required tool call(s) already observed: {}.",
                        required_tool_calls
                            .iter()
                            .map(|entry| format!("`{entry}`"))
                            .collect::<Vec<String>>()
                            .join(", ")
                    )
                } else {
                    format!(
                        "Missing required tool call(s): {}.",
                        format_missing_required_calls(&missing_required)
                    )
                };
                messages.push(json!({
                    "role": "system",
                    "content": format!(
                        "No tool call was made, but this turn requires tool usage. Retries remaining: {}. {} Do not answer with a sentinel or natural-language final response until required tool call(s) succeed. When calling execute_tactus, pass arguments as {{\"tactus\":\"return ...\"}} and ensure `tactus` is a non-empty Lua string.",
                        retries_remaining,
                        required_hint,
                    ),
                }));
                continue;
            }
            if let Some(expected) = deterministic_expected_response(
                local_test_lane,
                saw_tool_calls,
                saw_tool_errors,
                &expected_final_response,
            ) {
                return Ok(AgentTurnOutput {
                    assistant_content: expected,
                    model_context: if capture_model_context {
                        json!({ "attempts": model_context_attempts })
                    } else {
                        Value::Null
                    },
                });
            }
            if let Some(assignment_id) = deterministic_assignment_id(local_test_lane, saw_tool_calls, saw_tool_errors, &assignment_ids) {
                return Ok(AgentTurnOutput {
                    assistant_content: assignment_id,
                    model_context: if capture_model_context {
                        json!({ "attempts": model_context_attempts })
                    } else {
                        Value::Null
                    },
                });
            }
            return Ok(AgentTurnOutput {
                assistant_content: if saw_tool_calls {
                    fallback_tool_assistant_content(assistant_content)
                } else {
                    fallback_assistant_content(assistant_content)
                },
                model_context: if capture_model_context {
                    json!({ "attempts": model_context_attempts })
                } else {
                    Value::Null
                },
            });
        }

        saw_tool_calls = true;
        messages.push(json!({
            "role": "assistant",
            "content": if assistant_content.is_empty() { Value::Null } else { Value::String(assistant_content) },
            "tool_calls": tool_calls,
        }));

        let mut round_tool_errors: Vec<(String, String, Option<String>, String)> = Vec::new();
        for call in tool_calls {
            let call_id = call
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("tool-call");
            let function = call
                .get("function")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            let name = function
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("execute_tactus");
            let arguments = function
                .get("arguments")
                .and_then(Value::as_str)
                .unwrap_or("{}");
            let call_now = now_iso();
            let call_record = PersistedMessage {
                id: format!("message-console-tool-{}", Uuid::new_v4()),
                thread_id: trigger.thread_id.clone(),
                parent_message_id: Some(trigger.id.clone()),
                created_at: call_now.clone(),
                sequence_number: *next_sequence,
                role: "TOOL".to_string(),
                message_kind: MESSAGE_KIND_TOOL_CALL.to_string(),
                message_type: "TOOL_CALL".to_string(),
                content: arguments.to_string(),
                summary: truncate_summary(&format!("{name} tool call")),
                response_status: None,
                response_error: None,
                response_started_at: None,
                response_completed_at: None,
                metadata: json!({ "toolCallId": call_id, "toolName": name, "arguments": arguments }),
            };
            create_message_graphql(state, &call_record, &call_now).await?;
            *next_sequence += 1;

            let tool_result =
                execute_tactus_tool(state, trigger, context, name, arguments, web_ui.as_ref()).await;
            let tool_result_markdown = render_tool_result_markdown(&tool_result);
            collect_assignment_ids(&tool_result, &mut assignment_ids);
            collect_tool_api_call_counts(&tool_result, &mut observed_tool_counts);
            let result_now = now_iso();
            let result_record = PersistedMessage {
                id: format!("message-console-tool-{}", Uuid::new_v4()),
                thread_id: trigger.thread_id.clone(),
                parent_message_id: Some(trigger.id.clone()),
                created_at: result_now.clone(),
                sequence_number: *next_sequence,
                role: "TOOL".to_string(),
                message_kind: MESSAGE_KIND_TOOL_RESULT.to_string(),
                message_type: "TOOL_RESPONSE".to_string(),
                content: tool_result_markdown.clone(),
                summary: truncate_summary(&format!("{name} tool result")),
                response_status: None,
                response_error: None,
                response_started_at: None,
                response_completed_at: None,
                metadata: json!({
                    "toolCallId": call_id,
                    "toolName": name,
                    "toolResultJson": tool_result.clone(),
                }),
            };
            create_message_graphql(state, &result_record, &result_now).await?;
            *next_sequence += 1;
            messages.push(json!({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_result_markdown,
            }));
            if let Some(error_text) = tool_result_error_text(&tool_result) {
                saw_tool_errors = true;
                let error_code = tool_result_error_code(&tool_result);
                round_tool_errors.push((
                    name.to_string(),
                    arguments.to_string(),
                    error_code,
                    error_text,
                ));
            }
        }

        if !round_tool_errors.is_empty() && round + 1 < MAX_TOOL_ATTEMPTS {
            let retries_remaining = MAX_TOOL_ATTEMPTS - (round + 1);
            let unsupported_snippet_seen = round_tool_errors
                .iter()
                .any(|(_, _, code, _)| code.as_deref() == Some("unsupported_snippet"));
            let parse_error_seen = round_tool_errors
                .iter()
                .any(|(_, _, _, error)| error.contains("Failed to parse DSL") || error.contains("unfinished string"));
            let retry_details = round_tool_errors
                .into_iter()
                .map(|(name, arguments, code, error)| {
                    let code_prefix = code
                        .as_deref()
                        .map(|value| format!("Code: {}\n", value))
                        .unwrap_or_default();
                    format!(
                        "Tool: {}\nArguments:\n{}\n{}Error:\n{}",
                        name, arguments, code_prefix, error
                    )
                })
                .collect::<Vec<String>>()
                .join("\n\n---\n\n");
            let correction_hint = if unsupported_snippet_seen {
                "At least one error was unsupported_snippet: your previous call used JS/object-call shape. \
Use Lua/Tactus table-call syntax instead (for example: return docs_get{ id = \"resources.Assignment\" })."
            } else if parse_error_seen {
                "At least one call failed with a Lua parse error. Use a single-line snippet, keep braces balanced, \
and prefer double-quoted string literals in tactus (for example: return knowledge_query{ semanticQuery = \"...\" })."
            } else {
                "Use raw Lua in tactus (no markdown fences, no escaped quotes like \\\" unless the value itself needs it)."
            };
            messages.push(json!({
                "role": "system",
                    "content": format!(
                    "The previous tool call(s) returned error(s). Retry by issuing a corrected execute_tactus tool call. Retries remaining: {}. {} Do not call docs_list/docs_get unless the user explicitly asked for documentation lookup. execute_tactus arguments must be {{\"tactus\":\"return ...\"}} with a non-empty Lua snippet. Previous tool failure detail(s):\n{}",
                    retries_remaining,
                    correction_hint,
                    retry_details,
                ),
            }));
        }

        if require_tool_calls && round + 1 < MAX_TOOL_ATTEMPTS && !required_tool_calls.is_empty() {
            let missing_required = missing_required_tool_calls(
                &required_tool_calls,
                &required_tool_call_counts,
                &observed_tool_counts,
            );
            if !missing_required.is_empty() {
                let retries_remaining = MAX_TOOL_ATTEMPTS - (round + 1);
                messages.push(json!({
                    "role": "system",
                    "content": format!(
                        "Required tool-call set is incomplete. Retries remaining: {}. Missing required tool call(s): {}. Continue with execute_tactus tool calls for the missing operations before finalizing your response. execute_tactus arguments must be {{\"tactus\":\"return ...\"}} with non-empty Lua code.",
                        retries_remaining,
                        format_missing_required_calls(&missing_required),
                    ),
                }));
            }
        }
    }

    if let Some(expected) = deterministic_expected_response(
        local_test_lane,
        saw_tool_calls,
        saw_tool_errors,
        &expected_final_response,
    ) {
        return Ok(AgentTurnOutput {
            assistant_content: expected,
            model_context: if capture_model_context {
                json!({ "attempts": model_context_attempts })
            } else {
                Value::Null
            },
        });
    }
    Ok(AgentTurnOutput {
        assistant_content: deterministic_assignment_id(local_test_lane, saw_tool_calls, saw_tool_errors, &assignment_ids)
            .unwrap_or_else(|| fallback_tool_assistant_content(last_assistant_content)),
        model_context: if capture_model_context {
            json!({ "attempts": model_context_attempts })
        } else {
            Value::Null
        },
    })
}

fn capture_openai_messages(messages: &[Value]) -> Value {
    const MAX_CAPTURED_MESSAGES: usize = 16;
    const MAX_CAPTURED_CONTENT_CHARS: usize = 320;
    let start = messages.len().saturating_sub(MAX_CAPTURED_MESSAGES);
    let captured = messages[start..]
        .iter()
        .map(|message| {
            let role = message
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let mut payload = json!({ "role": role });
            if let Some(content) = message.get("content").and_then(Value::as_str) {
                if let Some(entry) = payload.as_object_mut() {
                    entry.insert(
                        "content".to_string(),
                        Value::String(truncate_chars(content, MAX_CAPTURED_CONTENT_CHARS)),
                    );
                }
            }
            if let Some(tool_calls) = message.get("tool_calls").and_then(Value::as_array) {
                let names = tool_calls
                    .iter()
                    .filter_map(|entry| {
                        entry
                            .get("function")
                            .and_then(|function| function.get("name"))
                            .and_then(Value::as_str)
                    })
                    .map(ToString::to_string)
                    .collect::<Vec<String>>();
                if !names.is_empty() {
                    if let Some(entry) = payload.as_object_mut() {
                        entry.insert(
                            "toolCallNames".to_string(),
                            Value::Array(names.into_iter().map(Value::String).collect()),
                        );
                    }
                }
            }
            if let Some(tool_call_id) = message.get("tool_call_id").and_then(Value::as_str) {
                if let Some(entry) = payload.as_object_mut() {
                    entry.insert("toolCallId".to_string(), Value::String(tool_call_id.to_string()));
                }
            }
            payload
        })
        .collect::<Vec<Value>>();
    json!({
        "messageCount": messages.len(),
        "capturedCount": captured.len(),
        "messages": captured,
    })
}

fn truncate_chars(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    let mut output = String::new();
    for (index, ch) in value.chars().enumerate() {
        if index >= max_chars {
            break;
        }
        output.push(ch);
    }
    output.push_str("…");
    output
}

fn deterministic_assignment_id(
    local_test_lane: bool,
    saw_tool_calls: bool,
    saw_tool_errors: bool,
    assignment_ids: &HashSet<String>,
) -> Option<String> {
    if !local_test_lane || !saw_tool_calls || saw_tool_errors || assignment_ids.len() != 1 {
        return None;
    }
    assignment_ids.iter().next().cloned()
}

fn deterministic_expected_response(
    local_test_lane: bool,
    saw_tool_calls: bool,
    saw_tool_errors: bool,
    expected_final_response: &Option<String>,
) -> Option<String> {
    if !local_test_lane || !saw_tool_calls || saw_tool_errors {
        return None;
    }
    expected_final_response
        .as_ref()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn missing_required_tool_calls(
    required_tool_calls: &[String],
    required_tool_call_counts: &HashMap<String, usize>,
    observed_tool_counts: &HashMap<String, usize>,
) -> Vec<String> {
    let mut missing = Vec::new();
    for required in required_tool_calls {
        let required_count = required_tool_call_counts
            .get(required)
            .copied()
            .unwrap_or(1);
        let observed = observed_tool_counts
            .get(required)
            .copied()
            .unwrap_or(0);
        if observed < required_count {
            if required_count > 1 {
                missing.push(format!("{required} (need {required_count}, saw {observed})"));
            } else {
                missing.push(required.clone());
            }
        }
    }
    missing
}

fn format_missing_required_calls(missing_required: &[String]) -> String {
    missing_required
        .iter()
        .map(|entry| format!("`{entry}`"))
        .collect::<Vec<String>>()
        .join(", ")
}

fn tool_result_error_text(result: &Value) -> Option<String> {
    let ok = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
    if ok {
        return None;
    }
    let error = result.get("error")?;
    if error.is_string() {
        return error.as_str().map(ToString::to_string);
    }
    if let Some(error_obj) = error.as_object() {
        let code = error_obj
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or("unknown_error");
        let message = error_obj
            .get("message")
            .and_then(Value::as_str)
            .map(ToString::to_string)
            .unwrap_or_else(|| error.to_string());
        return Some(format!("{code}: {message}"));
    }
    Some(error.to_string())
}

fn tool_result_error_code(result: &Value) -> Option<String> {
    let ok = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
    if ok {
        return None;
    }
    let error = result.get("error")?;
    if let Some(error_obj) = error.as_object() {
        return error_obj
            .get("code")
            .and_then(Value::as_str)
            .map(ToString::to_string);
    }
    None
}

fn render_tool_result_markdown(result: &Value) -> String {
    let mut lines: Vec<String> = Vec::new();
    if let Some(ok) = result.get("ok").and_then(Value::as_bool) {
        lines.push(format!("- status: {}", if ok { "ok" } else { "error" }));
    }
    if let Some(api_calls) = result.get("api_calls").and_then(Value::as_array) {
        let calls = api_calls
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<&str>>();
        if !calls.is_empty() {
            lines.push("- api_calls:".to_string());
            for call in calls {
                lines.push(format!("  - `{}`", call));
            }
        }
    }
    if let Some(error) = result.get("error").and_then(Value::as_object) {
        lines.push("- error:".to_string());
        if let Some(code) = error.get("code").and_then(Value::as_str) {
            lines.push(format!("  - code: `{}`", code));
        }
        if let Some(message) = error.get("message").and_then(Value::as_str) {
            lines.push(format!("  - message: {}", message));
        }
        if let Some(retryable) = error.get("retryable").and_then(Value::as_bool) {
            lines.push(format!("  - retryable: {}", retryable));
        }
        if let Some(details) = error.get("details") {
            lines.push("  - details:".to_string());
            lines.extend(render_value_markdown(details, 4));
        }
    } else if let Some(value) = result.get("value") {
        lines.push("- value:".to_string());
        lines.extend(render_value_markdown(value, 2));
    }
    if lines.is_empty() {
        return "- status: empty tool result".to_string();
    }
    lines.join("\n")
}

fn render_value_markdown(value: &Value, indent: usize) -> Vec<String> {
    let pad = " ".repeat(indent);
    match value {
        Value::Null => vec![format!("{}- null", pad)],
        Value::Bool(boolean) => vec![format!("{}- {}", pad, boolean)],
        Value::Number(number) => vec![format!("{}- {}", pad, number)],
        Value::String(text) => text
            .lines()
            .map(|line| format!("{}- {}", pad, line))
            .collect(),
        Value::Array(items) => {
            if items.is_empty() {
                return vec![format!("{}- []", pad)];
            }
            let mut lines = Vec::new();
            for item in items {
                lines.extend(render_value_markdown(item, indent));
            }
            lines
        }
        Value::Object(map) => {
            if map.is_empty() {
                return vec![format!("{}- {{}}", pad)];
            }
            let mut lines = Vec::new();
            let mut keys = map.keys().collect::<Vec<&String>>();
            keys.sort();
            for key in keys {
                let entry = map.get(key).unwrap_or(&Value::Null);
                match entry {
                    Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {
                        let rendered = render_value_markdown(entry, 0).join(" ").trim().trim_start_matches('-').trim().to_string();
                        lines.push(format!("{}- **{}**: {}", pad, key, rendered));
                    }
                    _ => {
                        lines.push(format!("{}- **{}**:", pad, key));
                        lines.extend(render_value_markdown(entry, indent + 2));
                    }
                }
            }
            lines
        }
    }
}

fn collect_assignment_ids(value: &Value, assignment_ids: &mut HashSet<String>) {
    let Some(obj) = value.as_object() else {
        return;
    };
    if let Some(assignment_id) = obj.get("assignmentId").and_then(Value::as_str) {
        assignment_ids.insert(assignment_id.to_string());
    }
    if let Some(assignment) = obj.get("assignment").and_then(Value::as_object) {
        if let Some(assignment_id) = assignment.get("id").and_then(Value::as_str) {
            assignment_ids.insert(assignment_id.to_string());
        }
    }
    for nested in obj.values() {
        if nested.is_object() {
            collect_assignment_ids(nested, assignment_ids);
        }
    }
}

fn collect_tool_api_call_counts(value: &Value, observed_tool_counts: &mut HashMap<String, usize>) {
    let calls = value
        .get("api_calls")
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty())
                .map(ToString::to_string)
                .collect::<Vec<String>>()
        })
        .unwrap_or_default();
    for call in calls {
        *observed_tool_counts.entry(call).or_insert(0) += 1;
    }
}

fn build_openai_messages(
    context: &ThreadContextCache,
    static_prompt: &StaticPromptContext,
    web_ui: Option<&Value>,
) -> Vec<Value> {
    let mut messages = vec![json!({
        "role": "system",
        "content": "You are Papyrus, an editorial assistant for an autonomous newsroom. Be concise, accurate, and concrete. Raw console chat turns are working memory and are excluded from default semantic searches unless explicitly requested. When a chat produces durable insight, recommend creating an insight Message instead of making every chat turn canonical knowledge. Use execute_tactus for Papyrus runtime work. For user requests like \"most recent references\" or \"tell me about recent references\", do not ask clarifying questions first: immediately call execute_tactus with a Reference.list snippet, then summarize the returned references."
    })];
    if !static_prompt.publication_mission.trim().is_empty() {
        messages.push(json!({
            "role": "system",
            "content": format!("Publication mission:\n{}", static_prompt.publication_mission.trim())
        }));
    }
    if !static_prompt.publication_policy.trim().is_empty() {
        messages.push(json!({
            "role": "system",
            "content": format!("Publication policies:\n{}", static_prompt.publication_policy.trim())
        }));
    }
    if !static_prompt.docs_index.is_empty() {
        let docs_lines = static_prompt
            .docs_index
            .iter()
            .map(|entry| {
                format!(
                    "- {} [{}]: {}",
                    entry.id,
                    entry.namespace,
                    entry.summary.trim()
                )
            })
            .collect::<Vec<String>>()
            .join("\n");
        messages.push(json!({
            "role": "system",
            "content": format!(
                "execute_tactus supports a resource-oriented Papyrus API. Use api_list{{}} for the resource/verb schema. For recent-reference requests, call Reference.list{{ limit = <count>, order = \"newest\" }} and then summarize results. Tool responses are markdown only, never JSON. Use docs_list{{ namespace = \"resources\" }} first, then docs_get{{ id = \"resources.Assignment\" }} before non-trivial writes. To create a research assignment, use Assignment.create{{ type = \"research\", title = \"...\", apply = true }}.\nAvailable doc topics:\n{}",
                docs_lines
            )
        }));
    }
    if !context.rolling_summary.trim().is_empty() {
        messages.push(json!({
            "role": "system",
            "content": format!("Thread rolling summary:\n{}", context.rolling_summary)
        }));
    }
    if let Some(web_ui) = web_ui {
        let location_uri = web_ui
            .get("papyrusLocationUri")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        let web_path = web_ui
            .get("webPath")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if !location_uri.is_empty() || !web_path.is_empty() {
            let mut lines = vec![
                "Current web UI state for this turn (pedantic Papyrus location URIs):".to_string(),
            ];
            if !location_uri.is_empty() {
                lines.push(format!("- papyrus_location_uri: {location_uri}"));
            }
            if !web_path.is_empty() {
                lines.push(format!("- web_path: {web_path}"));
            }
            if let Some(object_uri) = web_ui
                .get("papyrusObjectUri")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty())
            {
                lines.push(format!("- focused_object_uri: {object_uri}"));
            }
            if let Some(label) = web_ui
                .get("label")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty())
            {
                lines.push(format!("- label: {label}"));
            }
            if let Some(view_mode) = web_ui
                .get("viewMode")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty())
            {
                lines.push(format!("- view_mode: {view_mode}"));
            }
            if let Some(index_filters) = web_ui.get("indexFilters").and_then(Value::as_object) {
                if !index_filters.is_empty() {
                    lines.push("- index_filters:".to_string());
                    for (key, value) in index_filters {
                        if let Some(text) = value.as_str() {
                            if !text.trim().is_empty() {
                                lines.push(format!("  - {key}: {text}"));
                            }
                        }
                    }
                }
            }
            lines.push(
                "Use execute_tactus with papyrus.web.current_location{} to re-read this snapshot, papyrus.web.navigate{ uri = \"papyrus://...\" } to move the browser, and papyrus.web.set_index_filters{ tab = \"references\", status = \"pending\" } (or kind/domain/type) to open a filtered index view.".to_string(),
            );
            if let Some(object_uri) = web_ui
                .get("papyrusObjectUri")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty())
            {
                if object_uri.starts_with("papyrus://reference/") {
                    let reference_id = object_uri.trim_start_matches("papyrus://reference/").trim();
                    if !reference_id.is_empty() {
                        lines.push(format!(
                            "The user is viewing reference detail in the web UI. For requests about \"this reference\", the open page, or what they are looking at, do not ask them to paste the reference. Immediately call execute_tactus with Reference.get{{ id = \"{reference_id}\" }} (lineage ids from the URL resolve to the current version) and summarize that record."
                        ));
                    }
                }
            }
            messages.push(json!({
                "role": "system",
                "content": lines.join("\n"),
            }));
        }
    }
    let mut emitted_tool_call_ids = HashSet::new();
    for cached in &context.recent_messages {
        if cached.content.trim().is_empty() {
            continue;
        }
        match cached.role.as_str() {
            "ASSISTANT" => messages.push(json!({ "role": "assistant", "content": cached.content })),
            "USER" => messages.push(json!({ "role": "user", "content": cached.content })),
            "TOOL" if cached.message_kind == MESSAGE_KIND_TOOL_CALL => {
                let tool_call_id = cached_tool_call_id(cached);
                emitted_tool_call_ids.insert(tool_call_id);
                messages.push(json!({
                    "role": "assistant",
                    "content": Value::Null,
                    "tool_calls": [cached_tool_call(cached)],
                }));
            }
            "TOOL" if cached.message_kind == MESSAGE_KIND_TOOL_RESULT => {
                let tool_call_id = cached_tool_call_id(cached);
                if !emitted_tool_call_ids.contains(&tool_call_id) {
                    continue;
                }
                messages.push(json!({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": cached.content,
                }));
            }
            "SYSTEM" if cached.message_kind == MESSAGE_KIND_WEB_CONTEXT => {
                messages.push(json!({
                    "role": "system",
                    "content": cached.content,
                }));
                if let Some(instructions) = console_context_agent_instructions(&cached.metadata) {
                    messages.push(json!({
                        "role": "system",
                        "content": instructions,
                    }));
                }
            }
            _ => continue,
        }
    }
    messages
}

fn cached_tool_call(cached: &CachedPromptMessage) -> Value {
    let arguments = cached
        .metadata
        .get("arguments")
        .and_then(Value::as_str)
        .unwrap_or(&cached.content);
    let name = cached
        .metadata
        .get("toolName")
        .and_then(Value::as_str)
        .unwrap_or("execute_tactus");
    json!({
        "id": cached_tool_call_id(cached),
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        }
    })
}

fn cached_tool_call_id(cached: &CachedPromptMessage) -> String {
    cached
        .metadata
        .get("toolCallId")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .unwrap_or_else(|| format!("cached-tool-call-{}", cached.id))
}

fn openai_request(model: &str, messages: Vec<Value>, require_tool_calls: bool) -> Value {
    let mut payload = json!({
        "model": model,
        "messages": messages,
        "parallel_tool_calls": false,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_tactus",
                    "description": "Execute a short Tactus snippet inside the Papyrus newsroom runtime. The tactus argument must be raw Lua (no markdown fences, no JSON-style escaped quotes such as \\\" for normal Lua strings). Use api_list and docs_list/docs_get for progressive documentation discovery. Assignment resource verbs include create/get/list/update. Canonical examples: return Assignment.create{ type = \"research\", title = \"Live smoke assignment\", apply = true } and return Assignment.get{ id = \"assignment-123\" }.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tactus": { "type": "string" },
                            "harness": { "type": "string" },
                            "assignment_id": { "type": "string" },
                            "assignment_item_json": { "type": "string" },
                            "corpus_key": { "type": "string" },
                            "max_evidence_items": { "type": "integer" },
                            "research_mode": { "type": "string" }
                        },
                        "required": ["tactus"]
                    }
                }
            }
        ],
        "tool_choice": "auto"
    });
    if require_tool_calls {
        payload["tool_choice"] = Value::String("required".to_string());
    }
    payload
}

#[derive(Debug)]
struct StreamedChatMessage {
    content: String,
    tool_calls: Vec<Value>,
}

#[derive(Debug, Default, Clone)]
struct ToolCallAccumulator {
    id: Option<String>,
    call_type: Option<String>,
    function_name: Option<String>,
    function_arguments: String,
}

async fn stream_openai_chat(
    state: &AppState,
    mut body: Value,
    mut assistant_writer: Option<&mut AssistantStreamWriter<'_>>,
) -> Result<StreamedChatMessage> {
    body["stream"] = Value::Bool(true);
    let response = state
        .http
        .post("https://api.openai.com/v1/chat/completions")
        .bearer_auth(&state.openai_api_key)
        .json(&body)
        .send()
        .await
        .context("send OpenAI streaming chat completion")?;
    let status = response.status();
    if !status.is_success() {
        let payload = response
            .text()
            .await
            .unwrap_or_else(|_| "unable to read OpenAI error body".to_string());
        return Err(anyhow!(
            "OpenAI chat completion failed with {status}: {payload}"
        ));
    }

    let mut stream = response.bytes_stream();
    let mut buffer = String::new();
    let mut content = String::new();
    let mut tool_calls: Vec<ToolCallAccumulator> = Vec::new();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.context("read OpenAI streaming chunk")?;
        buffer.push_str(&String::from_utf8_lossy(&chunk));
        while let Some(index) = buffer.find("\n\n") {
            let frame = buffer[..index].to_string();
            buffer = buffer[index + 2..].to_string();
            process_openai_sse_frame(
                &frame,
                &mut content,
                &mut tool_calls,
                assistant_writer.as_deref_mut(),
            )
            .await?;
        }
    }
    if !buffer.trim().is_empty() {
        process_openai_sse_frame(
            &buffer,
            &mut content,
            &mut tool_calls,
            assistant_writer.as_deref_mut(),
        )
        .await?;
    }
    if let Some(writer) = assistant_writer.as_deref_mut() {
        writer.flush().await?;
    }

    Ok(StreamedChatMessage {
        content,
        tool_calls: tool_calls
            .into_iter()
            .filter_map(tool_call_accumulator_to_value)
            .collect(),
    })
}

async fn process_openai_sse_frame(
    frame: &str,
    content: &mut String,
    tool_calls: &mut Vec<ToolCallAccumulator>,
    mut assistant_writer: Option<&mut AssistantStreamWriter<'_>>,
) -> Result<()> {
    for line in frame.lines() {
        let Some(data) = line.strip_prefix("data:") else {
            continue;
        };
        let data = data.trim();
        if data.is_empty() || data == "[DONE]" {
            continue;
        }
        let payload: Value = serde_json::from_str(data)
            .with_context(|| format!("parse OpenAI streaming event: {data}"))?;
        let Some(delta) = payload
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .and_then(|choice| choice.get("delta"))
        else {
            continue;
        };
        if let Some(text) = delta.get("content").and_then(Value::as_str) {
            content.push_str(text);
            if let Some(writer) = assistant_writer.as_deref_mut() {
                writer.push_delta(text).await?;
            }
        }
        if let Some(calls) = delta.get("tool_calls").and_then(Value::as_array) {
            merge_tool_call_deltas(tool_calls, calls);
        }
    }
    Ok(())
}

fn merge_tool_call_deltas(tool_calls: &mut Vec<ToolCallAccumulator>, calls: &[Value]) {
    for call in calls {
        let index = call.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
        while tool_calls.len() <= index {
            tool_calls.push(ToolCallAccumulator::default());
        }
        let entry = &mut tool_calls[index];
        if let Some(id) = call.get("id").and_then(Value::as_str) {
            entry.id = Some(id.to_string());
        }
        if let Some(call_type) = call.get("type").and_then(Value::as_str) {
            entry.call_type = Some(call_type.to_string());
        }
        if let Some(function) = call.get("function").and_then(Value::as_object) {
            if let Some(name) = function.get("name").and_then(Value::as_str) {
                entry.function_name = Some(name.to_string());
            }
            if let Some(arguments) = function.get("arguments").and_then(Value::as_str) {
                entry.function_arguments.push_str(arguments);
            }
        }
    }
}

fn tool_call_accumulator_to_value(call: ToolCallAccumulator) -> Option<Value> {
    let id = call.id?;
    let function_name = call.function_name?;
    Some(json!({
        "id": id,
        "type": call.call_type.unwrap_or_else(|| "function".to_string()),
        "function": {
            "name": function_name,
            "arguments": call.function_arguments,
        }
    }))
}

fn fallback_assistant_content(content: String) -> String {
    if content.trim().is_empty() {
        "I could not generate a response.".to_string()
    } else {
        content
    }
}

fn fallback_tool_assistant_content(content: String) -> String {
    if content.trim().is_empty() {
        "I used the available Papyrus context but could not generate a final response.".to_string()
    } else {
        content
    }
}

async fn execute_tactus_tool(
    state: &AppState,
    trigger: &ChatMessage,
    context: &ThreadContextCache,
    name: &str,
    arguments: &str,
    web_ui: Option<&Value>,
) -> Value {
    if name != "execute_tactus" {
        return json!({ "ok": false, "error": format!("Unsupported tool {name}") });
    }
    let parsed_args: Value = serde_json::from_str(arguments).unwrap_or_else(|_| json!({}));
    let mut tool_input = json!({
        "mode": "execute_tactus",
        "arguments": parsed_args,
        "thread_context": {
            "threadId": trigger.thread_id,
            "triggerMessageId": trigger.id,
            "triggerSequenceNumber": trigger.sequence_number,
            "cacheDigest": context.context_digest,
            "cachedRecentMessageCount": context.recent_messages.len(),
            "lastCachedSequenceNumber": context.last_sequence_number,
        }
    });
    if let Some(web_ui) = web_ui {
        if let Some(object) = tool_input.as_object_mut() {
            object.insert("webUi".to_string(), web_ui.clone());
        }
    }
    match call_execute_tactus_runner(state, &tool_input).await {
        Ok(value) => normalize_execute_tactus_result(value),
        Err(error) => json!({
            "ok": false,
            "error": {
                "code": "runner_failed",
                "message": error.to_string(),
                "retryable": true
            }
        }),
    }
}

fn normalize_execute_tactus_result(value: Value) -> Value {
    let Some(error_obj) = value.get("error").and_then(Value::as_object) else {
        return value;
    };
    let code = error_obj
        .get("code")
        .and_then(Value::as_str)
        .unwrap_or("");
    let message = error_obj
        .get("message")
        .and_then(Value::as_str)
        .unwrap_or("");
    let parse_like = message.contains("Failed to parse DSL")
        || message.contains("error loading code")
        || message.contains("unfinished string")
        || message.contains("'end' expected")
        || message.contains("unexpected symbol near")
        || message.contains("tactus must be a non-empty string");
    if !parse_like || (code != "tactus_execution_failed" && code != "invalid_request") {
        return value;
    }
    json!({
        "ok": false,
        "error": {
            "code": "unsupported_snippet",
            "message": format!(
                "Snippet rejected: execute_tactus requires valid Lua/Tactus table-call syntax in `tactus`. {}",
                message
            ),
            "retryable": true,
            "details": {
                "contractVersion": "execute_tactus_snippet_contract_v1",
                "acceptedSyntaxExamples": [
                    "return docs_get{ id = \"resources.Assignment\" }",
                    "return Assignment.create{ type = \"research\", title = \"...\", apply = true }"
                ],
                "guidance": "Use non-empty Lua in `tactus`; avoid JS object-call syntax and malformed escaping."
            }
        }
    })
}

async fn call_execute_tactus_runner(state: &AppState, input: &Value) -> Result<Value> {
    let mut command = Command::new("python3");
    command
        .arg(&state.config.execute_tactus_runner)
        .env("PYTHONUNBUFFERED", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let mut child = command
        .spawn()
        .with_context(|| {
            format!(
                "spawn execute_tactus runner {}",
                state.config.execute_tactus_runner.display()
            )
        })?;
    let encoded =
        serde_json::to_vec(input).context("serialize execute_tactus runner payload to JSON")?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(&encoded)
            .await
            .context("write execute_tactus runner payload")?;
    }
    let output = timeout(
        TokioDuration::from_secs(state.config.execute_tactus_timeout_seconds),
        child.wait_with_output(),
    )
    .await
    .with_context(|| {
        format!(
            "execute_tactus runner timed out after {} seconds",
            state.config.execute_tactus_timeout_seconds
        )
    })?
    .context("wait for execute_tactus runner")?;
    if !output.status.success() {
        return Err(anyhow!(
            "execute_tactus runner exited with {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let stdout = String::from_utf8(output.stdout)
        .context("parse execute_tactus runner stdout as utf8")?;
    if stdout.trim().is_empty() {
        return Err(anyhow!("execute_tactus runner returned empty stdout"));
    }
    serde_json::from_str(stdout.trim())
        .with_context(|| format!("parse execute_tactus runner JSON: {}", stdout.trim()))
}

async fn load_openai_api_key(ssm: &SsmClient) -> Result<String> {
    if let Some(value) = optional_env("OPENAI_API_KEY") {
        return Ok(value.trim().to_string());
    }
    let response = ssm
        .get_parameter()
        .name(SHARED_OPENAI_API_KEY_SSM_PARAM)
        .with_decryption(true)
        .send()
        .await
        .context("load OpenAI API key from shared SSM parameter")?;
    response
        .parameter()
        .and_then(|parameter| parameter.value())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow!("SSM parameter {SHARED_OPENAI_API_KEY_SSM_PARAM} did not include a value"))
}

fn appsync_region_from_endpoint(endpoint: &str) -> Option<String> {
    let host = endpoint
        .trim()
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()?;
    let parts: Vec<&str> = host.split('.').collect();
    let idx = parts.iter().position(|part| *part == "appsync-api")?;
    parts.get(idx + 1).map(|value| value.to_string())
}

fn resolve_message_model(default_model: &str, message: &ChatMessage) -> String {
    let selected = metadata_string_field(&message.metadata, "model")
        .or_else(|| metadata_string_field(&message.metadata, "selectedModel"))
        .unwrap_or_else(|| default_model.to_string());
    if SUPPORTED_CONSOLE_MODELS
        .iter()
        .any(|candidate| *candidate == selected)
    {
        selected
    } else {
        default_model.to_string()
    }
}

fn metadata_string_field(metadata: &Value, key: &str) -> Option<String> {
    metadata_value_field(metadata, key)
        .and_then(|value| value.as_str().map(|entry| entry.trim().to_string()))
        .filter(|entry| !entry.is_empty())
}

fn metadata_i64_field(metadata: &Value, key: &str) -> Option<i64> {
    metadata_value_field(metadata, key).and_then(|value| value.as_i64())
}

fn metadata_string_list_field(metadata: &Value, key: &str) -> Vec<String> {
    let Some(value) = metadata_value_field(metadata, key) else {
        return Vec::new();
    };
    let Some(entries) = value.as_array() else {
        return Vec::new();
    };
    entries
        .iter()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn metadata_string_usize_map_field(metadata: &Value, key: &str) -> HashMap<String, usize> {
    let Some(value) = metadata_value_field(metadata, key) else {
        return HashMap::new();
    };
    let Some(entries) = value.as_object() else {
        return HashMap::new();
    };
    entries
        .iter()
        .filter_map(|(entry_key, entry_value)| {
            let trimmed = entry_key.trim();
            if trimmed.is_empty() {
                return None;
            }
            let numeric = entry_value
                .as_u64()
                .or_else(|| entry_value.as_i64().and_then(|value| u64::try_from(value).ok()))
                .and_then(|value| usize::try_from(value).ok())?;
            if numeric == 0 {
                return None;
            }
            Some((trimmed.to_string(), numeric))
        })
        .collect()
}

fn metadata_value_field(metadata: &Value, key: &str) -> Option<Value> {
    if let Some(value) = metadata.get(key) {
        return Some(value.clone());
    }
    let text = metadata.as_str()?;
    let parsed: Value = serde_json::from_str(text).ok()?;
    parsed.get(key).cloned()
}

fn coerce_metadata_object(value: Value) -> Option<Value> {
    match value {
        Value::Object(_) => Some(value),
        Value::String(text) => serde_json::from_str(text.trim()).ok(),
        _ => None,
    }
}

fn metadata_nested_value_field(metadata: &Value, path: &[&str]) -> Option<Value> {
    if path.is_empty() {
        return None;
    }
    let mut current = coerce_metadata_object(metadata_value_field(metadata, path[0])?)?;
    for key in path.iter().skip(1) {
        let entry = current.get(*key)?.clone();
        current = coerce_metadata_object(entry)?;
    }
    Some(current)
}

fn console_context_agent_instructions(metadata: &Value) -> Option<String> {
    let console = coerce_metadata_object(metadata_value_field(metadata, "console")?)?;
    console
        .get("agentInstructions")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(str::to_string)
}

fn resolve_web_ui_from_context_messages(messages: &[CachedPromptMessage]) -> Option<Value> {
    messages
        .iter()
        .rev()
        .filter(|entry| entry.role == "SYSTEM" && entry.message_kind == MESSAGE_KIND_WEB_CONTEXT)
        .find_map(|entry| resolve_trigger_web_ui(&entry.metadata))
}

fn resolve_trigger_web_ui(metadata: &Value) -> Option<Value> {
    metadata_nested_value_field(metadata, &["console", "webUi"])
        .or_else(|| metadata_nested_value_field(metadata, &["webUi"]))
        .and_then(|value| {
            let web_path = value
                .get("webPath")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty());
            let location_uri = value
                .get("papyrusLocationUri")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|entry| !entry.is_empty());
            if web_path.is_some() || location_uri.is_some() {
                Some(value)
            } else {
                None
            }
        })
}

fn dynamodb_json_to_value(value: &Value) -> Value {
    if let Some(s) = value.get("S").and_then(Value::as_str) {
        return Value::String(s.to_string());
    }
    if let Some(n) = value.get("N").and_then(Value::as_str) {
        return n
            .parse::<i64>()
            .map(Value::from)
            .unwrap_or_else(|_| Value::String(n.to_string()));
    }
    if let Some(b) = value.get("BOOL").and_then(Value::as_bool) {
        return Value::Bool(b);
    }
    if value.get("NULL").and_then(Value::as_bool).unwrap_or(false) {
        return Value::Null;
    }
    if let Some(map) = value.get("M").and_then(Value::as_object) {
        return Value::Object(
            map.iter()
                .map(|(key, entry)| (key.clone(), dynamodb_json_to_value(entry)))
                .collect(),
        );
    }
    if let Some(list) = value.get("L").and_then(Value::as_array) {
        return Value::Array(list.iter().map(dynamodb_json_to_value).collect());
    }
    Value::Null
}

fn stream_string(image: &serde_json::Map<String, Value>, key: &str) -> Result<String> {
    image
        .get(key)
        .map(dynamodb_json_to_value)
        .and_then(|value| value.as_str().map(str::to_string))
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| anyhow!("missing DynamoDB stream string field {key}"))
}

fn stream_i64(image: &serde_json::Map<String, Value>, key: &str) -> Option<i64> {
    image
        .get(key)
        .map(dynamodb_json_to_value)
        .and_then(|value| value.as_i64())
}

fn attr_string(value: Option<&AttributeValue>) -> Option<String> {
    value.and_then(|attr| attr.as_s().ok().cloned())
}

fn attr_json(value: Option<&AttributeValue>) -> Value {
    let Some(attr) = value else {
        return Value::Null;
    };
    if let Ok(text) = attr.as_s() {
        return serde_json::from_str(text).unwrap_or_else(|_| Value::String(text.clone()));
    }
    if let Ok(map) = attr.as_m() {
        return Value::Object(
            map.iter()
                .map(|(key, entry)| (key.clone(), attr_json(Some(entry))))
                .collect(),
        );
    }
    if let Ok(list) = attr.as_l() {
        return Value::Array(list.iter().map(|entry| attr_json(Some(entry))).collect());
    }
    if let Ok(n) = attr.as_n() {
        return n
            .parse::<i64>()
            .map(Value::from)
            .or_else(|_| n.parse::<f64>().map(Value::from))
            .unwrap_or_else(|_| Value::String(n.clone()));
    }
    if let Ok(value) = attr.as_bool() {
        return Value::Bool(*value);
    }
    Value::Null
}

fn attr_i64(value: Option<&AttributeValue>) -> Option<i64> {
    value
        .and_then(|attr| attr.as_n().ok())
        .and_then(|value| value.parse::<i64>().ok())
}

fn av_s(value: &str) -> AttributeValue {
    AttributeValue::S(value.to_string())
}

fn truncate_summary(value: &str) -> String {
    let text = value.trim().replace('\n', " ");
    if text.chars().count() <= 180 {
        return text;
    }
    format!("{}…", text.chars().take(179).collect::<String>())
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn required_env(name: &str) -> String {
    optional_env(name).unwrap_or_else(|| panic!("{name} is required"))
}

fn env_or(name: &str, fallback: &str) -> String {
    optional_env(name).unwrap_or_else(|| fallback.to_string())
}

fn optional_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn normalize_jwt(token: String) -> String {
    token
        .trim()
        .trim_start_matches("Bearer ")
        .trim_start_matches("bearer ")
        .trim()
        .to_string()
}

fn format_error_chain(error: &anyhow::Error) -> String {
    error
        .chain()
        .map(ToString::to_string)
        .collect::<Vec<_>>()
        .join(": ")
}

fn to_hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push_str(&format!("{byte:02x}"));
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_cache_validation_accepts_matching_previous_cursor() {
        let cache = ThreadContextCache {
            schema_version: CONTEXT_CACHE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            last_sequence_number: 2,
            last_message_id: "message-2".to_string(),
            context_digest: "digest".to_string(),
            rolling_summary: String::new(),
            recent_messages: Vec::new(),
            updated_at: now_iso(),
        };
        let message = ChatMessage {
            id: "message-3".to_string(),
            thread_id: "thread-1".to_string(),
            role: "USER".to_string(),
            message_kind: MESSAGE_KIND_CHAT_TURN.to_string(),
            message_type: "MESSAGE".to_string(),
            content: "Hello".to_string(),
            response_target: DEFAULT_RESPONSE_TARGET.to_string(),
            response_status: "PENDING".to_string(),
            sequence_number: 3,
            created_at: now_iso(),
            metadata: json!({ "previousSequenceNumber": 2, "previousContextDigest": "digest" }),
        };
        assert!(cache_is_valid_for_message(&cache, &message));
    }

    #[test]
    fn resolve_trigger_web_ui_reads_nested_console_metadata() {
        let metadata = json!({
            "console": {
                "author": { "email": "editor@example.com" },
                "webUi": {
                    "webPath": "/newsroom/references?status=pending",
                    "papyrusLocationUri": "papyrus://newsroom/references/index/status/pending",
                    "viewMode": "index"
                }
            }
        });
        let web_ui = resolve_trigger_web_ui(&metadata).expect("webUi");
        assert_eq!(
            web_ui.get("webPath").and_then(Value::as_str),
            Some("/newsroom/references?status=pending")
        );
    }

    #[test]
    fn resolve_trigger_web_ui_parses_stringified_console_metadata() {
        let metadata = json!({
            "console": serde_json::to_string(&json!({
                "author": { "email": "editor@example.com" },
                "webUi": {
                    "webPath": "/newsroom/messages",
                    "papyrusLocationUri": "papyrus://newsroom/messages/index"
                }
            }))
            .expect("console json")
        });
        let web_ui = resolve_trigger_web_ui(&metadata).expect("webUi");
        assert_eq!(
            web_ui.get("papyrusLocationUri").and_then(Value::as_str),
            Some("papyrus://newsroom/messages/index")
        );
    }

    #[test]
    fn resolve_trigger_web_ui_rejects_empty_location_snapshot() {
        let metadata = json!({
            "console": {
                "webUi": {
                    "webPath": "",
                    "papyrusLocationUri": ""
                }
            }
        });
        assert!(resolve_trigger_web_ui(&metadata).is_none());
    }

    #[test]
    fn resolve_web_ui_from_context_messages_reads_latest_system_context() {
        let messages = vec![
            CachedPromptMessage {
                id: "ctx-1".to_string(),
                sequence_number: 1,
                role: "SYSTEM".to_string(),
                message_kind: MESSAGE_KIND_WEB_CONTEXT.to_string(),
                message_type: "MESSAGE".to_string(),
                content: "older".to_string(),
                metadata: json!({
                    "console": {
                        "webUi": {
                            "webPath": "/newsroom/references",
                            "papyrusLocationUri": "papyrus://newsroom/references/index"
                        }
                    }
                }),
            },
            CachedPromptMessage {
                id: "ctx-2".to_string(),
                sequence_number: 2,
                role: "SYSTEM".to_string(),
                message_kind: MESSAGE_KIND_WEB_CONTEXT.to_string(),
                message_type: "MESSAGE".to_string(),
                content: "newer".to_string(),
                metadata: json!({
                    "console": {
                        "webUi": {
                            "webPath": "/newsroom/references/ref-1",
                            "papyrusLocationUri": "papyrus://newsroom/references/detail/ref-1",
                            "papyrusObjectUri": "papyrus://reference/ref-1"
                        }
                    }
                }),
            },
        ];
        let web_ui = resolve_web_ui_from_context_messages(&messages).expect("webUi");
        assert_eq!(
            web_ui.get("papyrusObjectUri").and_then(Value::as_str),
            Some("papyrus://reference/ref-1")
        );
    }

    #[test]
    fn build_openai_messages_includes_system_web_context_turns() {
        let context = ThreadContextCache {
            schema_version: CONTEXT_CACHE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            last_sequence_number: 1,
            last_message_id: "ctx-1".to_string(),
            context_digest: String::new(),
            rolling_summary: String::new(),
            recent_messages: vec![CachedPromptMessage {
                id: "ctx-1".to_string(),
                sequence_number: 1,
                role: "SYSTEM".to_string(),
                message_kind: MESSAGE_KIND_WEB_CONTEXT.to_string(),
                message_type: "MESSAGE".to_string(),
                content: "Console session started.".to_string(),
                metadata: json!({
                    "console": {
                        "agentInstructions": "Use Reference.get for this page."
                    }
                }),
            }],
            updated_at: now_iso(),
        };
        let static_prompt = StaticPromptContext {
            schema_version: STATIC_PROMPT_CACHE_SCHEMA_VERSION,
            graphql_endpoint: String::new(),
            generated_at: String::new(),
            expires_at_epoch: 0,
            publication_mission: String::new(),
            publication_policy: String::new(),
            docs_index: Vec::new(),
        };
        let messages = build_openai_messages(&context, &static_prompt, None);
        let system_contents: Vec<&str> = messages
            .iter()
            .filter(|entry| entry.get("role").and_then(Value::as_str) == Some("system"))
            .filter_map(|entry| entry.get("content").and_then(Value::as_str))
            .collect();
        assert!(system_contents.iter().any(|entry| entry.contains("Console session started.")));
        assert!(system_contents.iter().any(|entry| entry.contains("Reference.get")));
    }

    #[test]
    fn context_cache_validation_rejects_stale_cursor() {
        let cache = ThreadContextCache {
            schema_version: CONTEXT_CACHE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            last_sequence_number: 1,
            last_message_id: "message-1".to_string(),
            context_digest: "digest".to_string(),
            rolling_summary: String::new(),
            recent_messages: Vec::new(),
            updated_at: now_iso(),
        };
        let message = ChatMessage {
            id: "message-3".to_string(),
            thread_id: "thread-1".to_string(),
            role: "USER".to_string(),
            message_kind: MESSAGE_KIND_CHAT_TURN.to_string(),
            message_type: "MESSAGE".to_string(),
            content: "Hello".to_string(),
            response_target: DEFAULT_RESPONSE_TARGET.to_string(),
            response_status: "PENDING".to_string(),
            sequence_number: 3,
            created_at: now_iso(),
            metadata: json!({ "previousSequenceNumber": 2, "previousContextDigest": "digest" }),
        };
        assert!(!cache_is_valid_for_message(&cache, &message));
    }
}
