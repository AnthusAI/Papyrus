import { defineFunction } from "@aws-amplify/backend";

/** The public form receiving endpoint. Wired (table, Function URL, origins, output) by `wire.ts`. */
export const publicForms = defineFunction({
  name: "papyrus-public-forms",
  entry: "./handler.ts",
  timeoutSeconds: 10,
  memoryMB: 256,
  resourceGroupName: "data",
});
