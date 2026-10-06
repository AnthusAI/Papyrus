import { defineStorage } from "@aws-amplify/backend";

export const storage = defineStorage({
  name: "papyrusMedia",
  isDefault: true,
  access: (allow) => ({
    "media/*": [
      allow.guest.to(["read"]),
      allow.authenticated.to(["read"]),
      allow.groups(["editor", "admin"]).to(["read", "write", "delete"]),
    ],
    "corpora/*": [
      allow.groups(["editor", "admin"]).to(["read"]),
    ],
    "preview/*": [
      allow.groups(["editor", "admin"]).to(["read"]),
    ],
    "newsroom/*": [
      allow.groups(["editor", "admin"]).to(["read", "write", "delete"]),
    ],
  }),
});
