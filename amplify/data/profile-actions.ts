import { a } from "@aws-amplify/backend";
import { resolverEntry } from "./message-actions";

/**
 * A person's public handle is the name the public Messages export shows next to their messages. Only the person can set or clear
 * their own: the mutation has no profile argument, and the resolver finds the profile from the signed-in identity's sub through the
 * UserIdentity index (admins get no way to write another person's handle). Three steps run as one AppSync pipeline, each a
 * self-contained resolver file: find the caller's profile, check the handle against the rules and the unique index, write it.
 */
const people = (allow: any) => [allow.group("editor"), allow.group("admin")];
const onIdentities = (entry: string) => a.handler.custom({ dataSource: a.ref("UserIdentity"), entry: resolverEntry(entry) });
const onProfiles = (entry: string) => a.handler.custom({ dataSource: a.ref("UserProfile"), entry: resolverEntry(entry) });

export const profileActionsSchemaDefinitions = {
  setPublicHandle: a
    .mutation()
    .arguments({ handle: a.string() })
    .returns(a.ref("UserProfile"))
    .authorization(people)
    .handler([
      onIdentities("./resolvers/set-public-handle-find-profile.js"),
      onProfiles("./resolvers/set-public-handle-check.js"),
      onProfiles("./resolvers/set-public-handle-write.js"),
    ]),
};
