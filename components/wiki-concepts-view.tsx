"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { SemanticNodeRecord } from "../lib/category-repository";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import type { createSemanticGraphSnapshot } from "../lib/semantic-graph";
import {
  conceptEditedAt, conceptId, conceptTitle, conceptWikiPath, conceptsByTitle, recentlyEditedConcepts, resolveConceptLink,
} from "../lib/wiki";
import { MarkusIrPreview } from "./markus-ir-preview";
import { createWikiIndexPage, loadWikiIndexPage, type WikiIndexPage } from "./wiki-index-client";

type SemanticGraph = ReturnType<typeof createSemanticGraphSnapshot>;

const editedFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

function formatEdited(value: string): string {
  const parsed = new Date(value);
  return value && !Number.isNaN(parsed.getTime()) ? editedFormat.format(parsed) : "";
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

function ConceptLink({ children, demo, node, onOpen }: { children?: ReactNode; demo: boolean; node: SemanticNodeRecord; onOpen: (lineageId: string) => void }) {
  return <a className="wiki-link" data-wiki-concept-link={conceptId(node)} href={getNewsroomNavHref(conceptWikiPath(node), demo)} onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); onOpen(conceptId(node)); }}>{children ?? conceptTitle(node)}</a>;
}

function ConceptRows({ demo, nodes, onOpen, showEdited }: { demo: boolean; nodes: SemanticNodeRecord[]; onOpen: (lineageId: string) => void; showEdited?: boolean }) {
  if (!nodes.length) return <p className="wiki-empty">No concepts to show.</p>;
  return <ul className="wiki-concept-list">
    {nodes.map(node => <li key={conceptId(node)}>
      <ConceptLink demo={demo} node={node} onOpen={onOpen} />
      <span className="wiki-chip">{kindLabel(node.nodeKind)}</span>
      {showEdited && conceptEditedAt(node) && <span className="wiki-meta">edited {formatEdited(conceptEditedAt(node))}</span>}
    </li>)}
  </ul>;
}

function WikiIndexPageView({ demo, nodes, onOpen }: { demo: boolean; nodes: SemanticNodeRecord[]; onOpen: (lineageId: string) => void }) {
  const [page, setPage] = useState<WikiIndexPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let cancelled = false;
    loadWikiIndexPage(demo || isLocalPreviewEnabled()).then(loaded => { if (!cancelled) setPage(loaded); }).catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the wiki index."); });
    return () => { cancelled = true; };
  }, [demo]);
  const dynamicDirectives = useMemo(() => ({
    "recent-concepts": (attributes: Record<string, unknown>) => <ConceptRows demo={demo} nodes={recentlyEditedConcepts(nodes, { kind: typeof attributes.kind === "string" ? attributes.kind : null, limit: Number(attributes.limit) || 10 })} onOpen={onOpen} showEdited />,
    "concept-list": (attributes: Record<string, unknown>) => <ConceptRows demo={demo} nodes={conceptsByTitle(nodes, { kind: typeof attributes.kind === "string" ? attributes.kind : null, limit: Number(attributes.limit) || null })} onOpen={onOpen} />,
    "concept-count": (attributes: Record<string, unknown>) => <strong>{nodes.filter(node => !attributes.kind || node.nodeKind === attributes.kind).length}</strong>,
  }), [demo, nodes, onOpen]);
  const renderLink = (href: string, children: ReactNode) => {
    const node = resolveConceptLink(href, nodes);
    return node ? <ConceptLink demo={demo} node={node} onOpen={onOpen}>{children}</ConceptLink> : null;
  };
  if (error) return <p className="wiki-empty" role="alert">{error}</p>;
  if (!page) return <p className="wiki-empty">Loading the wiki…</p>;
  return <article className="wiki-page" data-wiki-index>
    <div className="wiki-page-tools">
      {page.itemId
        ? <Link className="wiki-tool-link" href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(page.itemId)}`, demo)}>Edit this page</Link>
        : <button className="wiki-tool-link" disabled={saving} onClick={() => { setSaving(true); createWikiIndexPage(demo || isLocalPreviewEnabled()).then(setPage).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not save the index.")).finally(() => setSaving(false)); }} type="button">{saving ? "Saving…" : "Save this page so it can be edited"}</button>}
    </div>
    <MarkusIrPreview bodyIr={page.bodyIr} dynamicDirectives={dynamicDirectives} renderLink={renderLink} />
  </article>;
}

function ConceptPageView({ demo, graph, node, nodes, onOpen }: { demo: boolean; graph: SemanticGraph; node: SemanticNodeRecord; nodes: SemanticNodeRecord[]; onOpen: (lineageId: string) => void }) {
  const lineage = conceptId(node);
  const groups = graph.neighbors("semanticNode", lineage);
  const references = graph.referencesForSemanticNode(lineage);
  const byLineage = new Map(nodes.map(candidate => [conceptId(candidate), candidate]));
  const aliases = (node.aliases ?? []).filter(Boolean) as string[];
  return <article className="wiki-page" data-wiki-concept={lineage}>
    <h1>{conceptTitle(node)}</h1>
    <p className="wiki-meta"><span className="wiki-chip">{kindLabel(node.nodeKind)}</span> {node.status !== "current" && <span className="wiki-chip">{node.status}</span>} {conceptEditedAt(node) && <>Last edited {formatEdited(conceptEditedAt(node))}</>}{node.versionCreatedBy ? ` by ${node.versionCreatedBy}` : ""}</p>
    {aliases.length > 0 && <p className="wiki-meta">Also known as {aliases.join(", ")}</p>}
    {node.description ? node.description.split(/\n{2,}/).map((paragraph, index) => <p key={index}>{paragraph}</p>) : <p className="wiki-empty">This concept has no description yet.</p>}
    <section data-wiki-section="connections">
      <h2>Connections</h2>
      {groups.length ? groups.map(group => <div className="wiki-connection-group" key={`${group.direction}-${group.predicate}`}>
        <h3>{group.label}</h3>
        <ul className="wiki-concept-list">
          {group.objects.map(object => {
            const target = object.kind === "semanticNode" ? byLineage.get(object.lineageId) : undefined;
            return <li key={`${object.kind}-${object.lineageId}`}>{target ? <ConceptLink demo={demo} node={target} onOpen={onOpen} /> : <span>{object.label}</span>}<span className="wiki-chip">{target ? kindLabel(target.nodeKind) : object.kind}</span></li>;
          })}
        </ul>
      </div>) : <p className="wiki-empty">No connections recorded.</p>}
    </section>
    <section data-wiki-section="references">
      <h2>References</h2>
      {references.length ? <ul className="wiki-concept-list">
        {references.map(reference => <li key={reference.lineageId}><Link href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(reference.lineageId)}`, demo)}>{reference.label}</Link></li>)}
      </ul> : <p className="wiki-empty">No references recorded.</p>}
    </section>
  </article>;
}

/**
 * The concept wiki: the front page is a content item whose Markus body can hold live components
 * (recently edited concepts, concept lists), and every concept in the knowledge graph is a page
 * linked to the concepts and references it connects to.
 */
export function WikiConceptsView({ demo = false, graph, initialNodeLineageId, nodes }: { demo?: boolean; graph: SemanticGraph; initialNodeLineageId?: string | null; nodes: SemanticNodeRecord[] }) {
  const [selected, setSelected] = useState<string | null>(initialNodeLineageId ?? null);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  useEffect(() => { setSelected(initialNodeLineageId ?? null); }, [initialNodeLineageId]);
  useEffect(() => {
    const onPop = () => {
      const match = window.location.pathname.match(/\/concepts\/([^/?#]+)/);
      setSelected(match ? decodeURIComponent(match[1]) : null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const open = (lineageId: string | null) => {
    setSelected(lineageId);
    const target = getNewsroomNavHref(lineageId ? `/newsroom/concepts/${encodeURIComponent(lineageId)}` : "/newsroom/concepts", demo);
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.pushState(null, "", target);
  };
  const node = selected ? nodes.find(candidate => conceptId(candidate) === selected || candidate.id === selected) ?? null : null;
  const kinds = useMemo(() => Array.from(new Set(nodes.map(candidate => candidate.nodeKind))).sort(), [nodes]);
  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return conceptsByTitle(nodes, { kind: kind || null }).filter(candidate => !needle || conceptTitle(candidate).toLowerCase().includes(needle) || (candidate.aliases ?? []).some(alias => alias?.toLowerCase().includes(needle)));
  }, [kind, nodes, search]);
  return <div className="wiki" data-wiki>
    <nav aria-label="Wiki" className="wiki-sidebar">
      <button className="wiki-home" data-wiki-home aria-current={node ? undefined : "page"} onClick={() => open(null)} type="button">Wiki home</button>
      <input aria-label="Search concepts" className="wiki-search" onChange={event => setSearch(event.target.value)} placeholder="Search concepts" value={search} />
      {kinds.length > 1 && <select aria-label="Concept kind" className="wiki-kind" onChange={event => setKind(event.target.value)} value={kind}>
        <option value="">All kinds</option>
        {kinds.map(option => <option key={option} value={option}>{kindLabel(option)}</option>)}
      </select>}
      <ul className="wiki-sidebar-list">
        {matches.map(candidate => <li key={conceptId(candidate)}><a aria-current={node && conceptId(node) === conceptId(candidate) ? "page" : undefined} href={getNewsroomNavHref(conceptWikiPath(candidate), demo)} onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); open(conceptId(candidate)); }}>{conceptTitle(candidate)}</a></li>)}
      </ul>
    </nav>
    <div className="wiki-main">
      {node
        ? <ConceptPageView demo={demo} graph={graph} node={node} nodes={nodes} onOpen={open} />
        : selected ? <p className="wiki-empty" role="alert">That concept page was not found.</p>
        : <WikiIndexPageView demo={demo} nodes={nodes} onOpen={open} />}
    </div>
  </div>;
}
