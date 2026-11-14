"use client";

import { CircleCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { callAnnouncements } from "../lib/announcements-client";
import { X_STATE_STORAGE_KEY, callbackUrl, failureText } from "../lib/announcements-model";
import { getPublicNewsroomBasePath, newsroomHref } from "../lib/newsroom-base-path";

type Outcome = { kind: "working" } | { kind: "connected"; handle: string } | { kind: "problem"; text: string };

/** Finishes the connection: checks the state the browser kept, then asks the announcements function to exchange the code. */
export function XCallback() {
  const [outcome, setOutcome] = useState<Outcome>({ kind: "working" });
  useEffect(() => {
    void (async () => {
      const query = new URLSearchParams(window.location.search);
      const kept = window.sessionStorage.getItem(X_STATE_STORAGE_KEY);
      window.sessionStorage.removeItem(X_STATE_STORAGE_KEY);
      if (query.get("error")) return setOutcome({ kind: "problem", text: `X did not connect the account: ${query.get("error_description") ?? query.get("error")}` });
      const code = query.get("code");
      const state = query.get("state");
      if (!code || !state) return setOutcome({ kind: "problem", text: "X did not send back a code. Choose Connect X account again." });
      if (!kept || kept !== state) return setOutcome({ kind: "problem", text: "This connection did not start in this browser. Choose Connect X account again." });
      const result = await callAnnouncements<{ status: { handle: string } }>("announcementsXComplete", {
        code, state, redirectUri: callbackUrl(window.location.origin, getPublicNewsroomBasePath()),
      });
      setOutcome(result.ok ? { kind: "connected", handle: result.status.handle } : { kind: "problem", text: failureText(result) });
    })();
  }, []);

  return (
    <main className="announcements-callback" data-x-callback={outcome.kind}>
      {outcome.kind === "working" ? <p>Finishing the connection with X…</p> : null}
      {outcome.kind === "connected" ? <p role="status"><CircleCheck aria-hidden="true" size={20} /> Connected: @{outcome.handle}</p> : null}
      {outcome.kind === "problem" ? <p role="alert"><TriangleAlert aria-hidden="true" size={20} /> {outcome.text}</p> : null}
      <Link href={newsroomHref("administration", "announcements")}>Back to Announcements</Link>
    </main>
  );
}
