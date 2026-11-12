const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const browser = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-story-schedule-ui.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });

for (const given of [
  "the Stories board with a scheduled Story, an overdue Story, a superseded Story and an unscheduled Story",
  "the Stories board with a scheduled Story",
  "the Stories board with an unscheduled Story open in its drawer",
  "the Stories board with a scheduled Story open in its drawer",
  "the Schedule page with four Stories this week and one the week after",
  "the Schedule page with four Stories this week",
  "the Schedule page on a screen 375 pixels wide",
  "the Schedule page, the board and an open drawer in light and dark",
]) Given(given, function () {});

for (const when of [
  "the editor looks at the cards",
  "the editor opens the Story, in New York and then from London",
  "the editor picks 20 November at 07:30, changes it to 21 November at 14:00, and then clears it",
  "the editor picks a new time while the save fails, and then saves again once it works",
  "the editor picks 02:30 on the night clocks go forward, and then 01:30 on the night they go back",
  "the editor opens it",
  "the editor tabs through the page",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-story-schedule-ui.ts (a real browser, local preview data, a fixed clock).
const outcomes = {
  'the scheduled card shows a calendar-clock icon and "Scheduled: Fri 13 Nov, 9:00 AM ET", the time in New York': "badge_states",
  'the overdue card shows a warning icon and "Overdue"': "badge_states",
  'the superseded card shows a slashed-circle icon and "Superseded: a newer version was saved"': "badge_states",
  "the unscheduled card shows no schedule line": "badge_states",
  'the drawer says "Scheduled for Fri 13 Nov 2026, 9:00 AM ET (New York), by Preview editor"': "drawer_sentence",
  'from London a small line adds "2:00 PM GMT your time"': "drawer_sentence",
  "the Publish button and the Draft state are as they were": "drawer_sentence",
  "each change shows in the drawer and on the card, and clearing takes both back": "set_and_clear",
  "the backend was asked only to schedule, with the UTC instant and never a draft save, a publish or a stage move": "set_and_clear",
  "the drawer says the schedule could not be saved, shows the saved time again and keeps the typed date and time": "failed_save",
  "a time that has already passed is refused before anything is sent": "failed_save",
  'the first is refused with "That time does not exist on 14 March in New York. Pick another time." and nothing is sent': "dst",
  'the second lists "01:30 EDT" and "01:30 EST", sends nothing until one is chosen, and then schedules the one chosen': "dst",
  "the current week is shown in New York time with each Story's time, state in words, icon and title": "calendar",
  "a plain list of the same Stories follows the calendar": "calendar",
  'choosing Month shows all five and choosing Day shows an empty day with "Nothing is scheduled today."': "calendar",
  'only one week of the schedule index is read at a time, and an empty week says "Nothing is scheduled this week." and offers "Schedule a Story"': "calendar",
  "every event is a focusable button, the list has a link for each Story, and Enter on an event opens its Story": "keyboard",
  "the week is shown as a list by day with the same four Stories and nothing scrolls sideways": "phone",
  "the badge and the drawer's schedule row fit the phone, with targets at least 36 pixels tall": "phone",
  "no element of the badge, the schedule row or the calendar draws a visible outline": "no_borders",
};
const exactly = (text) => new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
for (const [outcome, scenario] of Object.entries(outcomes)) Then(exactly(outcome), { timeout: 180000 }, async function () { await browser(scenario); });
