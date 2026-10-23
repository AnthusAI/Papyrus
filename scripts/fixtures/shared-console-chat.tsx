import "chatticus/chat.css";
import "../../components/papyrus-console-conversation.css";
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { PapyrusConsoleConversation, type ConsoleConversationMessage } from "../../components/papyrus-console-conversation";

function PapyrusHost() {
  const [messages, setMessages] = useState<ConsoleConversationMessage[]>([
    { id: "user", role: "USER", text: "Check the selected reference" },
    { id: "answer", role: "ASSISTANT", text: "**Ready** for editorial work. [Unsafe](javascript:alert(1))" },
    { id: "tool", role: "TOOL", text: "" },
  ]);
  const [sends, setSends] = useState(0);
  const [navigation, setNavigation] = useState(0);
  return <main>
    <output aria-label="Papyrus sends">{sends}</output>
    <output aria-label="Papyrus reference actions">{navigation}</output>
    <PapyrusConsoleConversation messages={messages} isSending={false} isRunning={false}
      onSendMessage={async (text) => {
        setSends((value) => value + 1);
        setMessages((current) => [...current, { id: "new-user", role: "USER", text },
          { id: "new-answer", role: "ASSISTANT", text: "Papyrus received the editorial request" }]);
      }} presentation={{ body: (id, body) => id === "tool"
        ? <button onClick={() => setNavigation((value) => value + 1)}>Open reference</button> : body }} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<PapyrusHost />);
