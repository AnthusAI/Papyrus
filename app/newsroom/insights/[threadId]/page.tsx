import { permanentRedirect } from "next/navigation";
import { toPublicNewsroomPath } from "../../../../lib/newsroom-base-path";

type NewsroomMessageThreadRedirectPageProps = {
  params: Promise<{ threadId: string }>;
};

export default async function NewsroomMessageThreadRedirectPage({ params }: NewsroomMessageThreadRedirectPageProps) {
  const { threadId } = await params;
  permanentRedirect(toPublicNewsroomPath(`/newsroom/messages/${encodeURIComponent(threadId)}`));
}
