import { permanentRedirect } from "next/navigation";
import { toPublicNewsroomPath } from "../../../lib/newsroom-base-path";

export default function NewsroomMessagesRedirectPage() {
  permanentRedirect(toPublicNewsroomPath("/newsroom/messages"));
}
