import { XCallback } from "../../../../../../components/x-callback";

export const dynamic = "force-dynamic";

/** Where X sends the owner back after approving (the callback URL entered in the X developer app). */
export default function XCallbackPage() {
  return <XCallback />;
}
