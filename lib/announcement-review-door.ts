"use client";

/** The announcement review of X story posts, sent as the signed-in person to the site's agent-policy function (lib/announcement-review-client.ts says why there). */
import { generateClient } from "aws-amplify/data";
import { configureAmplifyClient } from "../components/amplify-client-provider";
import { announcementReviewApi, type AnnouncementReviewApi } from "./announcement-review-client";

export const callAnnouncementReview: AnnouncementReviewApi = announcementReviewApi(async (request) => {
  configureAmplifyClient();
  return generateClient({ authMode: "userPool" }).graphql(request) as Promise<unknown>;
});
