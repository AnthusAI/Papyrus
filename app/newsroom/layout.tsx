import { NewsroomClientShell } from "../../components/newsroom-client-shell";

export default function NewsroomLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <NewsroomClientShell>{children}</NewsroomClientShell>;
}
