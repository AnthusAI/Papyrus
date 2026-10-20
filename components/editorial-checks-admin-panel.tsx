"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { describeProbability, type EditorialCheckResult } from "../lib/editorial-checks";
import {
  DEFAULT_EDITORIAL_SETTINGS,
  deletePolicy,
  draftQuestions,
  importStarterPack,
  listPolicies,
  loadSettings,
  recalibrate,
  savePolicy,
  saveSettings,
  tryPolicy,
  type EditorialPolicyRecord,
  type EditorialSettings,
} from "../lib/editorial-checks-client";

const STARTER_PACKS = [
  { name: "ai-writing-tells", label: "AI-writing tells" },
  { name: "plain-language", label: "Federal Plain Language Guidelines" },
  { name: "asd-ste100", label: "ASD-STE100 Simplified Technical English" },
] as const;
const POLICY_KEY = /^[a-z0-9][a-z0-9._-]*$/;

type Draft = {
  isNew: boolean;
  record: EditorialPolicyRecord;
  detectorsText: string;
  violatesText: string;
  compliesText: string;
};

function emptyPolicy(): EditorialPolicyRecord {
  return {
    id: "",
    policyKey: "",
    scope: "publication",
    version: 1,
    title: "",
    guidance: "",
    severity: "warn",
    enabled: true,
    detectors: [],
    examples: null,
    rewriteGuidance: null,
    source: "custom",
  };
}

function draftFrom(record: EditorialPolicyRecord, isNew: boolean): Draft {
  return {
    isNew,
    record,
    detectorsText: JSON.stringify(record.detectors, null, 2),
    violatesText: (record.examples?.violates ?? []).join("\n"),
    compliesText: (record.examples?.complies ?? []).join("\n"),
  };
}

function lines(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}

/** The policy as Limatus sees it (its key is the policy id). Throws on invalid detector JSON. */
function limatusPolicy(draft: Draft): Record<string, unknown> {
  const detectors = JSON.parse(draft.detectorsText || "[]") as unknown;
  if (!Array.isArray(detectors)) throw new Error("Detectors must be a JSON list.");
  const violates = lines(draft.violatesText);
  const complies = lines(draft.compliesText);
  return {
    id: draft.record.policyKey || "draft",
    version: draft.record.version,
    title: draft.record.title || "Draft policy",
    guidance: draft.record.guidance || "Draft policy.",
    severity: draft.record.severity,
    enabled: true,
    detectors,
    ...(violates.length || complies.length ? { examples: { violates, complies } } : {}),
    ...(draft.record.rewriteGuidance ? { rewriteGuidance: draft.record.rewriteGuidance } : {}),
  };
}

export function EditorialChecksAdminPanel() {
  const [policies, setPolicies] = useState<EditorialPolicyRecord[] | null>(null);
  const [settings, setSettings] = useState<EditorialSettings>(DEFAULT_EDITORIAL_SETTINGS);
  const [settingsExist, setSettingsExist] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [starterPack, setStarterPack] = useState<string>(STARTER_PACKS[0].name);
  const [message, setMessage] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [tryText, setTryText] = useState("");
  const [tryResult, setTryResult] = useState<EditorialCheckResult | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [loadedPolicies, loadedSettings] = await Promise.all([listPolicies(), loadSettings()]);
      setPolicies(loadedPolicies);
      setSettings(loadedSettings.settings);
      setSettingsExist(loadedSettings.exists);
    } catch (error) {
      setMessage(`Error: ${error instanceof Error ? error.message : "could not load editorial checks"}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (label: string, action: () => Promise<string | void>) => {
    setWorking(label);
    setMessage(null);
    try {
      const outcome = await action();
      if (outcome) setMessage(outcome);
    } catch (error) {
      setMessage(`Error: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setWorking(null);
    }
  };

  const patchDraft = (patch: Partial<EditorialPolicyRecord>) => setDraft((current) => (current ? { ...current, record: { ...current.record, ...patch } } : current));

  const save = () =>
    run("save", async () => {
      if (!draft) return;
      const key = draft.record.policyKey.trim();
      if (!POLICY_KEY.test(key)) throw new Error("The key must be lowercase letters, digits, dots, hyphens or underscores.");
      if (!draft.record.title.trim() || !draft.record.guidance.trim()) throw new Error("A policy needs a title and guidance.");
      const policy = limatusPolicy(draft);
      const record: EditorialPolicyRecord = {
        ...draft.record,
        id: draft.isNew ? `${draft.record.scope}#${key}` : draft.record.id,
        policyKey: key,
        version: draft.isNew ? 1 : draft.record.version + 1,
        detectors: policy.detectors as unknown[],
        examples: (policy.examples as EditorialPolicyRecord["examples"]) ?? null,
      };
      await savePolicy(record, draft.isNew);
      setDraft(null);
      await refresh();
      return `Saved ${record.title} (version ${record.version}).`;
    });

  return (
    <section aria-labelledby="newsroom-editorial-checks-title" data-news-desk-admin-panel="editorial-checks">
      <h3 id="newsroom-editorial-checks-title">Editorial checks</h3>
      <p>
        Policies the article editor checks drafts against. Rules match words and patterns; judgment questions are answered by a decision model, sentence by sentence.
        Findings are advice: editors can dismiss them, and publishing is never blocked.
      </p>
      <p aria-live="polite" role="status">
        {working ? <><Spinner /> Working…</> : message}
      </p>

      <h4>Policies</h4>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => { setDraft(draftFrom(emptyPolicy(), true)); setTryResult(null); }} size="sm" type="button">New policy</Button>
        <select aria-label="Starter pack" onChange={(event) => setStarterPack(event.target.value)} value={starterPack}>
          {STARTER_PACKS.map((pack) => <option key={pack.name} value={pack.name}>{pack.label}</option>)}
        </select>
        <Button
          disabled={working !== null}
          onClick={() => run("import", async () => {
            const outcome = await importStarterPack(starterPack);
            await refresh();
            const label = STARTER_PACKS.find((pack) => pack.name === starterPack)?.label ?? starterPack;
            return `${label}: ${outcome.created} policies added, ${outcome.skipped} already present.`;
          })}
          size="sm"
          type="button"
          variant="outline"
        >
          Add starter pack
        </Button>
        <Button
          disabled={working !== null}
          onClick={() => run("recalibrate", async () => {
            const outcome = await recalibrate();
            await refresh();
            const notes = outcome.detectors.filter((d) => d.note).map((d) => `${d.policyId}/${d.detectorId}: ${d.note}`);
            return `Recalibrated ${outcome.updated} ${outcome.updated === 1 ? "policy" : "policies"} from editors' decisions.${notes.length ? ` ${notes.join("; ")}` : ""}`;
          })}
          size="sm"
          type="button"
          variant="outline"
        >
          Recalibrate from editors&apos; decisions
        </Button>
      </div>
      {policies === null ? <p>Loading…</p> : policies.length === 0 ? <p>No policies yet. Add the starter pack or write one.</p> : (
        <table data-editorial-policies>
          <thead>
            <tr><th scope="col">Policy</th><th scope="col">Applies to</th><th scope="col">Severity</th><th scope="col">Detectors</th><th scope="col">On</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {policies.map((policy) => (
              <tr data-editorial-policy-row={policy.id} key={policy.id}>
                <td>{policy.title}<br /><small>{policy.policyKey} · v{policy.version}</small></td>
                <td>{policy.scope === "publication" ? "Whole publication" : `Desk: ${policy.scope}`}</td>
                <td>{policy.severity}</td>
                <td>{policy.detectors.length === 0 ? "Guidance only" : policy.detectors.length}</td>
                <td>
                  <input
                    aria-label={`${policy.title} enabled`}
                    checked={policy.enabled}
                    onChange={(event) => void run("toggle", async () => {
                      await savePolicy({ ...policy, enabled: event.target.checked, version: policy.version + 1 }, false);
                      await refresh();
                    })}
                    type="checkbox"
                  />
                </td>
                <td>
                  <button onClick={() => { setDraft(draftFrom(policy, false)); setTryResult(null); }} type="button">Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {draft ? (
        <form
          className="space-y-2"
          data-editorial-policy-form
          onSubmit={(event) => { event.preventDefault(); void save(); }}
        >
          <h4>{draft.isNew ? "New policy" : `Edit ${draft.record.title}`}</h4>
          <label>Key <Input disabled={!draft.isNew} onChange={(event) => patchDraft({ policyKey: event.target.value })} value={draft.record.policyKey} /></label>
          <label>Title <Input onChange={(event) => patchDraft({ title: event.target.value })} value={draft.record.title} /></label>
          <label>
            Applies to (publication, or a desk key){" "}
            <Input disabled={!draft.isNew} onChange={(event) => patchDraft({ scope: event.target.value.trim() || "publication" })} value={draft.record.scope} />
          </label>
          <label>
            Severity{" "}
            <select onChange={(event) => patchDraft({ severity: event.target.value as EditorialPolicyRecord["severity"] })} value={draft.record.severity}>
              <option value="error">Must fix</option>
              <option value="warn">Should fix</option>
              <option value="info">Consider</option>
            </select>
          </label>
          <label>Guidance (what the policy asks, in plain words) <Textarea onChange={(event) => patchDraft({ guidance: event.target.value })} rows={3} value={draft.record.guidance} /></label>
          <label>How to fix it (for rewrite suggestions) <Textarea onChange={(event) => patchDraft({ rewriteGuidance: event.target.value || null })} rows={2} value={draft.record.rewriteGuidance ?? ""} /></label>
          <label>Examples that break it (one per line) <Textarea onChange={(event) => setDraft({ ...draft, violatesText: event.target.value })} rows={3} value={draft.violatesText} /></label>
          <label>Examples that follow it (one per line) <Textarea onChange={(event) => setDraft({ ...draft, compliesText: event.target.value })} rows={3} value={draft.compliesText} /></label>
          <label>
            Detectors (JSON; see <code>limatus schema policy-pack-v1</code>)
            <Textarea className="font-mono text-xs" onChange={(event) => setDraft({ ...draft, detectorsText: event.target.value })} rows={10} value={draft.detectorsText} />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={working !== null || !draft.record.title.trim() || !draft.record.guidance.trim()}
              onClick={() => run("draft", async () => {
                const drafted = await draftQuestions(draft.record.title, draft.record.guidance);
                const existing = JSON.parse(draft.detectorsText || "[]") as unknown[];
                setDraft({ ...draft, detectorsText: JSON.stringify([...existing, ...drafted.detectors], null, 2) });
                return `Added ${drafted.detectors.length} drafted judgment question(s). Review them before saving. ${drafted.notes.join(" ")}`;
              })}
              type="button"
              variant="outline"
            >
              Draft judgment questions
            </Button>
            <Button disabled={working !== null} type="submit">Save</Button>
            {!draft.isNew ? (
              <Button
                onClick={() => run("delete", async () => {
                  await deletePolicy(draft.record.id);
                  setDraft(null);
                  await refresh();
                  return "Policy deleted.";
                })}
                type="button"
                variant="outline"
              >
                Delete
              </Button>
            ) : null}
            <Button onClick={() => setDraft(null)} type="button" variant="ghost">Cancel</Button>
          </div>

          <fieldset className="space-y-2" data-editorial-try>
            <legend>Try it on sample text (nothing is saved)</legend>
            <Textarea onChange={(event) => setTryText(event.target.value)} rows={4} value={tryText} />
            <Button
              disabled={working !== null || !tryText.trim()}
              onClick={() => run("try", async () => {
                setTryResult(await tryPolicy(limatusPolicy(draft), tryText));
              })}
              size="sm"
              type="button"
              variant="outline"
            >
              Try policy
            </Button>
            {tryResult ? (
              tryResult.findings.length === 0 ? <p>No findings.</p> : (
                <ul data-editorial-try-findings>
                  {tryResult.findings.map((finding) => (
                    <li key={finding.id}>
                      {finding.status === "review" ? "Unsure: " : ""}“{finding.excerpt || "whole text"}” {describeProbability(finding) ? `(${describeProbability(finding)})` : ""}
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </fieldset>
        </form>
      ) : null}

      <h4>Settings</h4>
      <form
        className="space-y-2"
        data-editorial-settings
        onSubmit={(event) => {
          event.preventDefault();
          void run("settings", async () => {
            await saveSettings(settings, settingsExist);
            setSettingsExist(true);
            return "Settings saved.";
          });
        }}
      >
        <label><input checked={settings.enabled} data-editorial-enabled onChange={(event) => setSettings({ ...settings, enabled: event.target.checked })} type="checkbox" /> Run editorial checks for this publication (turning this off stops checks and rewrites; policies are kept)</label>
        <label><input checked={settings.lanes.rules} onChange={(event) => setSettings({ ...settings, lanes: { ...settings.lanes, rules: event.target.checked } })} type="checkbox" /> Rule checks</label>
        <label><input checked={settings.lanes.classifier} onChange={(event) => setSettings({ ...settings, lanes: { ...settings.lanes, classifier: event.target.checked } })} type="checkbox" /> Judgment checks (decision model)</label>
        <label><input checked={settings.checkWhileTyping} onChange={(event) => setSettings({ ...settings, checkWhileTyping: event.target.checked })} type="checkbox" /> Check while editors type (after a short pause)</label>
        <label><input checked={settings.publishWarning} onChange={(event) => setSettings({ ...settings, publishWarning: event.target.checked })} type="checkbox" /> Warn before publishing with open findings</label>
        <label>Decision model <Input onChange={(event) => setSettings({ ...settings, classifierModel: event.target.value })} value={settings.classifierModel} /></label>
        <label>Rewrite model <Input onChange={(event) => setSettings({ ...settings, rewriteModel: event.target.value })} value={settings.rewriteModel} /></label>
        <label>Time limit for judgment checks (seconds, under 28) <Input max={26} min={1} onChange={(event) => setSettings({ ...settings, deadlineSeconds: Number(event.target.value) })} type="number" value={settings.deadlineSeconds} /></label>
        <label>Input-token budget per check <Input min={1} onChange={(event) => setSettings({ ...settings, maxInputTokens: Number(event.target.value) })} type="number" value={settings.maxInputTokens} /></label>
        <label>Past decisions shown to each judgment question <Input max={32} min={0} onChange={(event) => setSettings({ ...settings, maxExamplesPerQuestion: Number(event.target.value) })} type="number" value={settings.maxExamplesPerQuestion} /></label>
        <label>House guidance for rewrites <Textarea onChange={(event) => setSettings({ ...settings, guidance: event.target.value })} rows={3} value={settings.guidance} /></label>
        <Button disabled={working !== null} type="submit">Save settings</Button>
      </form>
    </section>
  );
}
