import { DynamoDBClient, UpdateItemCommand } from "@aws-sdk/client-dynamodb";
import { getLambdaDataClient, LAMBDA_DATA_AUTH_MODE } from "../shared/lambda-data-client";
import {
  configFromEnvironment,
  handlePublicFormRequest,
  type FormSubmissionRecord,
  type FunctionUrlEvent,
  type RateLimiter,
  type SubmissionStore,
} from "./core";

const dynamo = new DynamoDBClient({});

/** Counters live in a TTL table; the window number is part of the key, so a window simply stops being read. */
const limiter: RateLimiter = {
  async hit(scope, subject, windowSeconds, limit) {
    const nowSeconds = Math.floor(Date.now() / 1000);
    const window = Math.floor(nowSeconds / windowSeconds);
    const result = await dynamo.send(
      new UpdateItemCommand({
        TableName: process.env.PAPYRUS_PUBLIC_FORMS_TABLE,
        Key: { pk: { S: `${scope}#${subject}#${windowSeconds}#${window}` } },
        UpdateExpression: "ADD hits :one SET expiresAt = :expires",
        ExpressionAttributeValues: { ":one": { N: "1" }, ":expires": { N: String((window + 2) * windowSeconds) } },
        ReturnValues: "UPDATED_NEW",
      }),
    );
    return Number(result.Attributes?.hits?.N ?? "0") <= limit;
  },
};

const store: SubmissionStore = {
  async save(record: FormSubmissionRecord) {
    const client = await getLambdaDataClient();
    const created = await client.models.Message.create(record as never, { authMode: LAMBDA_DATA_AUTH_MODE });
    if (created.errors?.length) throw new Error("Message create failed");
  },
};

export const handler = (event: FunctionUrlEvent) =>
  handlePublicFormRequest(event, configFromEnvironment(process.env), { store, limiter });
