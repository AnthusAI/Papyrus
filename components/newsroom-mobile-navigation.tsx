"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { BookOpen, ClipboardList, House, MessageCircle, MessagesSquare } from "lucide-react";

const ICONS = { overview: House, articles: ClipboardList, references: BookOpen, messages: MessagesSquare };

export function NewsroomMobileNavigation({ items, activeTab, chat, more }: {
  items: readonly { key: string; label: string; description: string; href: string }[];
  activeTab: string;
  chat?: { open: boolean; onOpen: () => void };
  more: ReactNode;
}) {
  return <nav className="organizer-bottom-nav" aria-label="Primary newsroom navigation"><ul>
    {items.map(item => {
      if (item.key === "messages" && chat) return <li key="chat"><button className="organizer-chat" type="button" aria-label="Open private chat" aria-expanded={chat.open} aria-controls="papyrus-console-panel" onClick={chat.onOpen}><MessageCircle size={18} aria-hidden="true" /><span>Chat</span></button></li>;
      const Icon = ICONS[item.key as keyof typeof ICONS];
      return <li key={item.key}><Link href={item.href} title={item.description} aria-label={item.label} aria-current={activeTab === item.key ? "page" : undefined}><Icon size={18} aria-hidden="true" /><span>{item.label}</span></Link></li>;
    })}
    <li>{more}</li>
  </ul></nav>;
}
