"use client";

import { ConceptBody, DraftBody, EmailBody, Heading, RequestBody, type DetailProps } from "./needs-me-bodies";
import { ReferenceBody } from "./needs-me-reference-detail";
import { isReferenceLike } from "./needs-me-shared";

export type { DecisionExtras } from "./needs-me-bodies";

/** The detail pane for any item: the same shell, with a body that fits the type. */
export function NeedsMeDetail(props: DetailProps) {
  const { item } = props;
  const { payload } = item;
  return (
    <div className="flex flex-col gap-4 p-4 font-sans" data-needs-me-detail={item.id} data-needs-me-detail-type={item.type}>
      {/* A Reference puts its title first and carries these badges under it. */}
      {payload.kind === "reference" ? null : <Heading item={item} />}
      {payload.kind === "reference" && isReferenceLike(item) ? <ReferenceBody {...props} payload={payload} /> : null}
      {payload.kind === "draft" ? <DraftBody {...props} payload={payload} /> : null}
      {payload.kind === "request" ? <RequestBody {...props} payload={payload} /> : null}
      {payload.kind === "email" ? <EmailBody {...props} payload={payload} /> : null}
      {payload.kind === "concept" ? <ConceptBody item={item} /> : null}
    </div>
  );
}
