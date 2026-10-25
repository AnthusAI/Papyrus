import { createSiteHostedRunHandler } from "chatticus/chat-runtime";

export const handler = createSiteHostedRunHandler(process.env);
