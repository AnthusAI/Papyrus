"use client";

import { AtSign, CircleAlert, CircleCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { PUBLIC_HANDLE_TAKEN_MESSAGE, checkPublicHandle, publicHandleRefusalMessage } from "../lib/public-handle";

export const PUBLIC_HANDLE_HELP = "Shown next to your messages on the public site. Leave empty to be shown as Editor. Never your email.";

type Outcome = { state: "idle" } | { state: "saving" } | { state: "saved"; message: string } | { state: "error"; message: string };

export type PublicHandleFieldProps = {
  storedHandle: string | null;
  save: (handle: string | null) => Promise<string | null>;
};

function refusalText(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (/taken/i.test(message)) return PUBLIC_HANDLE_TAKEN_MESSAGE;
  if (/reserved/i.test(message)) return "That handle is reserved";
  if (/3 to 24/.test(message)) return publicHandleRefusalMessage("length");
  return "The handle could not be saved. Try again.";
}

export function PublicHandleField({ storedHandle, save }: PublicHandleFieldProps) {
  const [draft, setDraft] = useState(storedHandle ?? "");
  const [stored, setStored] = useState(storedHandle);
  const [outcome, setOutcome] = useState<Outcome>({ state: "idle" });

  useEffect(() => {
    setStored(storedHandle);
    setDraft(storedHandle ?? "");
  }, [storedHandle]);

  const run = async (handle: string | null) => {
    setOutcome({ state: "saving" });
    try {
      const next = await save(handle);
      setStored(next);
      setDraft(next ?? "");
      setOutcome({ state: "saved", message: next ? `Saved. Your messages show as ${next}.` : "Cleared. Your messages show as Editor." });
    } catch (error) {
      setOutcome({ state: "error", message: refusalText(error) });
    }
  };

  const submit = () => {
    if (!draft.trim()) {
      void run(null);
      return;
    }
    const check = checkPublicHandle(draft);
    if (!check.valid) {
      setOutcome({ state: "error", message: publicHandleRefusalMessage(check.reason) });
      return;
    }
    void run(check.handle);
  };

  const busy = outcome.state === "saving";
  const unchanged = draft.trim().toLowerCase() === (stored ?? "");

  return (
    <section className="settings-section public-handle" aria-labelledby="settings-public-handle-title" data-public-handle>
      <div className="public-handle__heading">
        <p id="settings-public-handle-title">Public handle</p>
        <span>{stored ? `Shown as ${stored}` : "Shown as Editor"}</span>
      </div>
      <form
        className="public-handle__form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="public-handle__field">
          <AtSign aria-hidden="true" className="public-handle__icon" size={18} />
          <span className="public-handle__label">Public handle</span>
          <input
            aria-describedby="settings-public-handle-help settings-public-handle-status"
            autoCapitalize="none"
            autoComplete="off"
            autoCorrect="off"
            className="public-handle__input"
            disabled={busy}
            maxLength={40}
            onChange={(event) => {
              setDraft(event.target.value);
              if (outcome.state !== "saving") setOutcome({ state: "idle" });
            }}
            placeholder="your-handle"
            spellCheck={false}
            type="text"
            value={draft}
          />
        </label>
        <button className="public-handle__save" disabled={busy || unchanged} type="submit">
          {busy ? "Saving" : "Save"}
        </button>
      </form>
      <p className="public-handle__help" id="settings-public-handle-help">{PUBLIC_HANDLE_HELP}</p>
      <p
        aria-live="polite"
        className="public-handle__status"
        data-public-handle-state={outcome.state}
        id="settings-public-handle-status"
        role="status"
      >
        {outcome.state === "error" ? (
          <>
            <CircleAlert aria-hidden="true" size={16} />
            <span>{outcome.message}</span>
          </>
        ) : outcome.state === "saved" ? (
          <>
            <CircleCheck aria-hidden="true" size={16} />
            <span>{outcome.message}</span>
          </>
        ) : null}
      </p>
    </section>
  );
}
