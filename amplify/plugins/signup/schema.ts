import { a } from "@aws-amplify/backend";
import { signupSubmit } from "./function/resource";

const SIGNUP_READ_GROUPS = ["editor", "admin"];

/**
 * SignupEntry is never guest-readable and has no create rule for anyone: only the
 * submitSignup function (IAM) writes it. Editors and admins list it; admins delete.
 */
export function signupSchemaDefinitions() {
  return {
    SignupEntry: a
      .model({
        id: a.id().required(),
        form: a.string().required(),
        value: a.string().required(),
        submittedAt: a.datetime().required(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [
        index("form").sortKeys(["submittedAt"]).queryField("listSignupEntriesByFormAndSubmittedAt"),
      ])
      .authorization((allow) => [
        allow.groups(SIGNUP_READ_GROUPS).to(["read"]),
        allow.group("admin").to(["read", "delete"]),
      ]),
    SignupReceipt: a.customType({
      status: a.string().required(),
      message: a.string(),
    }),
    submitSignup: a
      .mutation()
      .arguments({
        form: a.string().required(),
        value: a.string().required(),
        renderedAt: a.string().required(),
        website: a.string(),
      })
      .returns(a.ref("SignupReceipt"))
      .authorization((allow) => [allow.guest()])
      .handler(a.handler.function(signupSubmit)),
  };
}
