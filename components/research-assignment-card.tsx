"use client";

import { BanIcon, CheckCircle2Icon, CircleHelpIcon, ClockIcon, ExternalLinkIcon, Loader2Icon, MinusCircleIcon, SearchCheckIcon, SearchIcon, TriangleAlertIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { assignmentStateView } from "../lib/assign-research";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { verdictLabel, type ClaimVerdict, type PacketSource, type ResearchPacketView } from "../lib/research-packet";
import { failureReasonOf, type TrailAssignment } from "../lib/story-reporting-trail";

const stateIcons = { waiting: ClockIcon, running: Loader2Icon, finished: CheckCircle2Icon, failed: XCircleIcon, other: CircleHelpIcon } as const;

const verdictIcons = { needs_check: SearchCheckIcon, rejected: BanIcon, unchecked: MinusCircleIcon } as const;

function SourceLinks({ sources }: { sources: PacketSource[] }) {
  if (!sources.length) return null;
  return <span className="research-sources">{sources.map(source => <a data-research-source={source.rank} href={source.url} key={source.rank} rel="noreferrer" target="_blank"><ExternalLinkIcon aria-hidden="true" size={12} /> {source.title}</a>)}</span>;
}

/** The packet of a finished research assignment: summary, angle, claims with their sources, disagreements, open questions, and what could not be verified. */
export function ResearchPacket({ packet }: { packet: ResearchPacketView }) {
  return <div className="research-packet" data-research-packet>
    <p className="research-packet-summary" data-research-packet-summary>{packet.summary}</p>
    {packet.recommendedAngle && <p className="research-packet-angle"><strong>Recommended angle.</strong> {packet.recommendedAngle}</p>}
    {packet.factCheckSummary && <p className="research-packet-angle" data-research-fact-check><strong>Fact check.</strong> {packet.factCheckSummary}</p>}
    {packet.readingSummary && <p className="research-packet-angle" data-research-reading><strong>Reading.</strong> {packet.readingSummary}{packet.notOpened.map(url => <span key={url}> <a data-research-not-opened href={url} rel="noreferrer" target="_blank">{url}</a></span>)}</p>}
    {packet.claims.length > 0 && <div data-research-claims><h4>Claims</h4><ul>{packet.claims.map(claim => <li key={claim.claim}>{claim.claim} {claim.snippetOnly && <span data-research-snippet-only>Search snippet only.</span>} <SourceLinks sources={claim.sources} /></li>)}</ul></div>}
    {packet.disagreements.length > 0 && <div data-research-disagreements><h4>Where sources disagree</h4><ul>{packet.disagreements.map(item => <li key={item.topic}><strong>{item.topic}</strong><ul>{item.positions.map(position => <li key={position.position}>{position.position} <SourceLinks sources={position.sources} /></li>)}</ul></li>)}</ul></div>}
    {packet.openQuestions.length > 0 && <div data-research-open-questions><h4>Open questions</h4><ul>{packet.openQuestions.map(question => <li key={question}>{question}</li>)}</ul></div>}
    {packet.directionGaps.length > 0 && <div className="research-unverified" data-research-direction-gaps><h4><TriangleAlertIcon aria-hidden="true" size={14} /> Named in the direction, not covered</h4><ul>{packet.directionGaps.map(gap => <li key={gap.name}><strong>{gap.name}</strong> {gap.note}</li>)}</ul></div>}
    {packet.unverifiedClaims.length > 0 && <div className="research-unverified" data-research-unverified><h4><TriangleAlertIcon aria-hidden="true" size={14} /> Could not verify</h4><ul>{packet.unverifiedClaims.map(item => <li key={item.claim}><span className="research-verdict" data-research-verdict={item.verdict ?? "needs_check"}>{(() => { const VerdictIcon = verdictIcons[(item.verdict ?? "needs_check") as ClaimVerdict]; return <VerdictIcon aria-hidden="true" size={12} />; })()} {verdictLabel(item.verdict)}</span> {item.claim} <SourceLinks sources={item.sources} />{item.reasons.length > 0 && <ul className="research-reasons">{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}</li>)}</ul></div>}
  </div>;
}

/**
 * One assignment in the Work section. A research assignment shows the editor's direction, its state in words and with an icon (waiting, running, finished,
 * failed with the reason) and, once finished, its packet. Other assignments keep the plain row.
 */
export function ResearchAssignmentCard({ assignment, demo, formatTimestamp }: { assignment: TrailAssignment; demo: boolean; formatTimestamp: (value: string | null | undefined) => string }) {
  const view = assignmentStateView(assignment.status);
  const StateIcon = stateIcons[view.state];
  const reason = failureReasonOf(assignment);
  return <div className="research-assignment" data-research-assignment={assignment.id} data-research-state={view.state}>
    <div className="story-trail-row">
      <strong><SearchIcon aria-hidden="true" size={14} /> Research assignment</strong>
      <span className="research-state" data-research-state-label><StateIcon aria-hidden="true" className={view.state === "running" ? "assign-research-spin" : undefined} size={13} /> {view.label}</span>
      <span className="story-trail-meta">{formatTimestamp(assignment.createdAt)}</span>
    </div>
    {assignment.direction && <p className="research-direction" data-research-direction>{assignment.direction}</p>}
    {reason && <p className="research-failure" data-research-failure><XCircleIcon aria-hidden="true" size={14} /> {reason}</p>}
    {assignment.packet && <ResearchPacket packet={assignment.packet} />}
    {assignment.status === "completed" && !assignment.packet && <p className="story-trail-meta" data-research-no-packet>The research finished, but its packet could not be read here.</p>}
    <Link href={getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignment.id)}`, demo)}>Open assignment</Link>
  </div>;
}
