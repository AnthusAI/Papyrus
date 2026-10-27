import "chatticus/chat.css";
import "../../components/papyrus-console-conversation.css";
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { PapyrusConsoleFrame } from "../../components/papyrus-console-frame";
import { PapyrusPrivateChatPanel } from "../../components/papyrus-private-chat-panel";

function Fixture() {
  const [open, setOpen] = useState(false);
  const available = !new URLSearchParams(location.search).has("unauthorized");
  return <PapyrusConsoleFrame available={available} open={open} reserveSpace={open} onOpen={() => setOpen(true)} onClose={() => setOpen(false)} page={
    <div className="newsroom-organizer" data-sidebar-collapsed="true">
      <div className="organizer-workspace">
        <header className="organizer-topbar"><a className="organizer-masthead" href="#overview">Papyrus</a><h1>Notification Center</h1><div className="organizer-header-actions"><a href="#settings">Settings</a><button>Search</button>{available && !open ? <button className="edition-progress__button--console" aria-label="Open console" onClick={() => setOpen(true)}>Console</button> : null}</div><button className="organizer-account">Editor</button></header>
        <main className="organizer-main"><a href="#references">References</a><div style={{ height: 1800 }}>Synthetic newsroom content</div></main>
      </div>
      <nav className="organizer-bottom-nav"><ul><li><a href="#overview">Overview</a></li><li><a href="#references">References</a></li></ul></nav>
    </div>
  }>{open ? <PapyrusPrivateChatPanel onClose={() => setOpen(false)} /> : null}</PapyrusConsoleFrame>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
