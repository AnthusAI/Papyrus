import { notFound } from "next/navigation";
import { StoryShareSignIn } from "../../../../components/story-share-sign-in";
import { SHARE_TOKEN_PATTERN } from "../../../../lib/story-share-view";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in to read a draft", robots: { index: false, follow: false } };

type SharePageProps = { params: Promise<{ token: string }> };

export default async function StoryShareSignInPage({ params }: SharePageProps) {
  const { token } = await params;
  if (!SHARE_TOKEN_PATTERN.test(token)) notFound();
  return <StoryShareSignIn token={token} />;
}
