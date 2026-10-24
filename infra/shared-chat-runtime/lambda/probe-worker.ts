import { createSiteHostedProbeHandler } from "chatticus/chat-runtime";

export const handler = createSiteHostedProbeHandler(process.env);
