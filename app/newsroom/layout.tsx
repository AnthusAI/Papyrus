// Component rules only (no reset, no theme): the Cyclotron review control and status widget.
import "cyclotron/styles/components.css";
import { NewsroomClientShell } from "../../components/newsroom-client-shell";

export default function NewsroomLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <NewsroomClientShell>{children}</NewsroomClientShell>;
}
