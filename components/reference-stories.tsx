"use client";

import { FileTextIcon, LinkIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { referenceRoleLabel, type ReferenceStory } from "../lib/story-reporting-trail";
import { loadStoriesBasedOnReference } from "./story-reporting-trail-client";

/**
 * The stories made from one Reference: each links to the story's own page. The stories' text is their own; this list is the other end
 * of the link the story view shows under References.
 */
export function ReferenceStories({ demo = false, referenceLineageId }: { demo?: boolean; referenceLineageId: string }) {
  const [stories, setStories] = useState<ReferenceStory[] | null>(null);
  useEffect(() => {
    let active = true;
    setStories(null);
    loadStoriesBasedOnReference(referenceLineageId, demo).then(rows => { if (active) setStories(rows); }).catch(() => { if (active) setStories([]); });
    return () => { active = false; };
  }, [demo, referenceLineageId]);
  if (!stories?.length) return null;
  return <section aria-label="Stories based on this Reference" className="reference-stories" data-reference-stories={referenceLineageId}>
    <h3>Stories based on this Reference</h3>
    <ul>
      {stories.map(story => <li data-reference-story={story.lineageId} key={story.relationId}>
        <FileTextIcon aria-hidden="true" size={16} />
        <Link href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(story.itemId)}`, demo)}>{story.title ?? story.lineageId}</Link>
        <span className="story-trail-role">{story.role === "based_on" ? <LinkIcon aria-hidden="true" size={13} /> : null}{referenceRoleLabel(story.role)}</span>
        {story.stage && <span className="story-trail-meta">{story.stage}</span>}
      </li>)}
    </ul>
  </section>;
}
