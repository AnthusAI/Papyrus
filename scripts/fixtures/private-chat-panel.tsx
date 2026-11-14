import "chatticus/chat.css";
import "../../components/papyrus-console-conversation.css";
import React from "react";
import { createRoot } from "react-dom/client";
import { PapyrusPrivateChatPanel } from "../../components/papyrus-private-chat-panel";

createRoot(document.getElementById("root")!).render(<PapyrusPrivateChatPanel onClose={() => {}} />);
