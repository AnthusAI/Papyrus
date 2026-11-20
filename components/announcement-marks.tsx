"use client";

import {
  Ban, Bot, CalendarCheck, CircleCheck, CircleHelp, CircleX, ClockAlert, FlaskConical, Flag, Hand, Hourglass, PencilLine, Replace, Send, ShieldAlert, Undo2, UserCheck,
  type LucideIcon,
} from "lucide-react";

/**
 * Each mark the backend names (`lines.py`, `approval_words.py`) is a Lucide icon drawn beside the words, never in place of them. The backend and this table are kept in step by
 * `features_backend/announcements/announcement-list-marks.feature`: a mark the backend can say that is not here fails that spec, so no line ever shows an icon of a different meaning.
 */
export const MARK_ICONS: Record<string, LucideIcon> = {
  "pencil-line": PencilLine,
  "calendar-check": CalendarCheck,
  send: Send,
  ban: Ban,
  "circle-check": CircleCheck,
  "circle-x": CircleX,
  "flask-conical": FlaskConical,
  "undo-2": Undo2,
  replace: Replace,
  "clock-alert": ClockAlert,
  "circle-help": CircleHelp,
  flag: Flag,
  "shield-alert": ShieldAlert,
  bot: Bot,
  "user-check": UserCheck,
  hourglass: Hourglass,
  hand: Hand,
};

/** The icon of a mark; the words beside it always say what it means. */
export function MarkIcon({ mark, size = 14 }: { mark: string; size?: number }) {
  const Icon = MARK_ICONS[mark];
  return Icon ? <Icon aria-hidden="true" size={size} data-mark={mark} /> : null;
}
