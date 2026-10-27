import "chatticus/chat.css";
import "../../components/papyrus-console-conversation.css";
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { PapyrusConsoleFrame } from "../../components/papyrus-console-frame";
import { PapyrusPrivateChatPanel } from "../../components/papyrus-private-chat-panel";
import { NewsroomMobileNavigation } from "../../components/newsroom-mobile-navigation";
import { useConsoleVisibility } from "../../components/use-console-visibility";
import { Menu } from "lucide-react";

function Fixture() {
  const { open, openConsole, closeConsole } = useConsoleVisibility({ persist: false });
  const [moreOpen, setMoreOpen] = useState(false);
  const available = !new URLSearchParams(location.search).has("unauthorized");
  return <PapyrusConsoleFrame available={available} open={open} reserveSpace={open} onClose={closeConsole} page={
    <div className="newsroom-organizer" data-sidebar-collapsed="true">
      <div className="organizer-workspace">
        <header className="organizer-topbar"><a className="organizer-masthead" href="#overview">Papyrus</a><h1>Notification Center</h1><div className="organizer-header-actions"><a href="#settings">Settings</a><button>Search</button>{available && !open ? <button className="edition-progress__button--console" aria-label="Open console" onClick={openConsole}>Console</button> : null}</div><button className="organizer-account">Editor</button></header>
        <main className="organizer-main"><a href="#references">References</a><div style={{ height: 1800 }}>Synthetic newsroom content</div></main>
      </div>
      <NewsroomMobileNavigation activeTab="overview" items={[
        { key: "overview", label: "Overview", description: "Overview", href: "#overview" },
        { key: "articles", label: "Stories", description: "Stories", href: "#stories" },
        { key: "references", label: "References", description: "References", href: "#references" },
        { key: "messages", label: "Messages", description: "Messages", href: "#messages" },
      ]} chat={available ? { open, onOpen: openConsole } : undefined} more={<button className="organizer-more" type="button" aria-label="More" onClick={() => setMoreOpen(value => !value)}><Menu size={18} aria-hidden="true" /><span>More</span></button>} />
      {moreOpen ? <nav aria-label="All workspaces"><a href="#messages">Messages</a></nav> : null}
    </div>
  }>{open ? <PapyrusPrivateChatPanel onClose={closeConsole} /> : null}</PapyrusConsoleFrame>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
