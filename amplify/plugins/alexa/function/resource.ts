import { defineFunction } from "@aws-amplify/backend";

/** TypeScript, bundled by Amplify (esbuild), so `ask-sdk-core` and the plugin's own modules ship inside the function. */
export const alexaSkill = defineFunction({
  name: "papyrus-alexa-skill",
  entry: "./handler.ts",
  // Alexa waits 8 seconds for a skill response.
  timeoutSeconds: 8,
  memoryMB: 512,
  resourceGroupName: "data",
});
