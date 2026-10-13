"use client";

import { generateClient } from "aws-amplify/data";
import amplifyOutputs from "papyrus-amplify-outputs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { signupForms, type PluginOutputs } from "../lib/plugin-settings";
import { signupEntriesToCsv, type SignupEntryRecord } from "../lib/signup-csv";

const LIST_QUERY = `query ListSignupEntries($form: String!, $nextToken: String) {
  listSignupEntriesByFormAndSubmittedAt(form: $form, sortDirection: DESC, limit: 200, nextToken: $nextToken) {
    items { id form value submittedAt }
    nextToken
  }
}`;

type ListResult = { data?: { listSignupEntriesByFormAndSubmittedAt?: { items: SignupEntryRecord[]; nextToken?: string | null } }; errors?: { message?: string }[] };

async function loadAllEntries(form: string): Promise<SignupEntryRecord[]> {
  const client = generateClient({ authMode: "userPool" });
  const entries: SignupEntryRecord[] = [];
  let nextToken: string | null | undefined;
  do {
    const result = (await client.graphql({ query: LIST_QUERY, variables: { form, nextToken } })) as ListResult;
    if (result.errors?.length) throw new Error(result.errors[0]?.message ?? "Could not load signups.");
    const page = result.data?.listSignupEntriesByFormAndSubmittedAt;
    entries.push(...(page?.items ?? []));
    nextToken = page?.nextToken;
  } while (nextToken);
  return entries;
}

export function SignupEntriesPanel() {
  const forms = useMemo(() => signupForms(amplifyOutputs as PluginOutputs), []);
  const [form, setForm] = useState(forms[0] ?? "");
  const [entries, setEntries] = useState<SignupEntryRecord[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!form) return;
    setEntries(null);
    setProblem(null);
    try {
      setEntries(await loadAllEntries(form));
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Could not load signups.");
    }
  }, [form]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const exportCsv = () => {
    if (!entries) return;
    const url = URL.createObjectURL(new Blob([signupEntriesToCsv(entries)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `signups-${form}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section aria-labelledby="newsroom-signups-title" data-news-desk-admin-panel="signups">
      <h3 id="newsroom-signups-title">Signups</h3>
      <p>Addresses people entered in the site&apos;s signup forms. Only editors and admins can see them.</p>
      <label>
        Form{" "}
        <select value={form} onChange={(event) => setForm(event.target.value)} disabled={forms.length < 2}>
          {forms.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </label>{" "}
      <button type="button" onClick={() => void refresh()}>Refresh</button>{" "}
      <button type="button" onClick={exportCsv} disabled={!entries || entries.length === 0}>Export CSV</button>
      <p role="status" aria-live="polite">
        {problem ? `Error: ${problem}` : entries === null ? "Loading..." : `${entries.length} ${entries.length === 1 ? "entry" : "entries"}`}
      </p>
      {entries && entries.length > 0 ? (
        <table>
          <thead>
            <tr><th scope="col">Submitted</th><th scope="col">Address</th></tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}><td>{entry.submittedAt}</td><td>{entry.value}</td></tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
