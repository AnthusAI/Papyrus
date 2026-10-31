import { a } from "@aws-amplify/backend";
import { prospectusAuthorizeStep, resolverEntry } from "./message-actions";

/**
 * A person's public handle is the name the public Messages export shows next to their messages. Only the person can set or clear
 * their own: the mutation has no profile argument, and the resolver finds the profile from the signed-in identity's sub through the
 * UserIdentity index (admins get no way to write another person's handle). Five steps run as one AppSync pipeline, each a
 * self-contained resolver file: find the caller's profile, read it, claim the handle (rules, then a conditional put of a
 * PublicHandleClaim keyed by the lowercase handle), write it, and release the claim nobody should hold (the old handle, or the new
 * one when the write failed).
 */
const people = (allow: any) => [allow.group("editor"), allow.group("admin")];
const onIdentities = (entry: string) => a.handler.custom({ dataSource: a.ref("UserIdentity"), entry: resolverEntry(entry) });
const onProfiles = (entry: string) => a.handler.custom({ dataSource: a.ref("UserProfile"), entry: resolverEntry(entry) });
const onClaims = (entry: string) => a.handler.custom({ dataSource: a.ref("PublicHandleClaim"), entry: resolverEntry(entry) });

export const buildProfileActionsSchemaDefinitions = (prospectusAuthorize: boolean) => ({
  setPublicHandle: a
    .mutation()
    .arguments({ handle: a.string() })
    .returns(a.ref("UserProfile"))
    .authorization(people)
    .handler([
      ...(prospectusAuthorize ? [prospectusAuthorizeStep()] : []),
      onIdentities("./resolvers/set-public-handle-find-profile.js"),
      onProfiles("./resolvers/set-public-handle-read-profile.js"),
      onClaims("./resolvers/set-public-handle-claim.js"),
      onProfiles("./resolvers/set-public-handle-write.js"),
      onClaims("./resolvers/set-public-handle-release.js"),
    ]),
});

export const profileActionsSchemaDefinitions = buildProfileActionsSchemaDefinitions(false);
