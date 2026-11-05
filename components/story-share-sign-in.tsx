"use client";

import { useEffect, useState } from "react";
import { loadReaderSessionSnapshot } from "./reader-auth-state";
import { ReaderAuthControl } from "./reader-auth-control";

/**
 * Where a signed-in share link sends a visitor who is not signed in (docs/story-share-links.md). Signing in comes back to this page, and once there is a session
 * the visitor goes on to the link itself, where the newsroom's function checks that they are an editor or admin.
 */
export function StoryShareSignIn({ token }: { token: string }) {
  const [phase, setPhase] = useState<"checking" | "signedOut" | "going">("checking");

  useEffect(() => {
    let active = true;
    void loadReaderSessionSnapshot().then((snapshot) => {
      if (!active) return;
      if (snapshot.auth.status === "signedIn") {
        setPhase("going");
        window.location.replace(`/api/share/${encodeURIComponent(token)}`);
      } else {
        setPhase("signedOut");
      }
    });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main className="mx-auto grid min-h-screen max-w-md place-items-center p-6" data-story-share-sign-in={phase}>
      <section className="space-y-3 rounded-xl bg-card p-6" aria-live="polite">
        <h1 className="m-0 font-sans text-xl font-semibold tracking-tight">Sign in to read this draft</h1>
        <p className="m-0 text-sm text-muted-foreground">This draft was shared with people who are signed in to the newsroom. Sign in, and you will come straight back to it.</p>
        {phase === "signedOut" ? <ReaderAuthControl showIdentity /> : null}
      </section>
    </main>
  );
}
