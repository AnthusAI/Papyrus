import { redirect } from "next/navigation";
import { toPublicNewsroomPath } from "../../../lib/newsroom-base-path";

export default function NewsroomWorkRedirectPage() {
  redirect(toPublicNewsroomPath("/newsroom/board"));
}
