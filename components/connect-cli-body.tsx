"use client";

import { CheckIcon, CopyIcon, DownloadIcon, InfoIcon, LaptopIcon, SmartphoneIcon, UserCheckIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { SITE_BRAND } from "../lib/site-brand";
import { CLI_INSTALL_ALTERNATIVE, type CliConnectPlan } from "../lib/cli-connect";

/** One command in a flat, rounded block with a copy button. The button changes its icon and words when it has copied, never its colour alone. */
function CommandLine({ command, label }: { command: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 2500);
  };
  return (
    <div className="connect-cli-row" data-connect-command-row>
      <code aria-label={label} className="connect-cli-command" data-connect-command>{command}</code>
      <button aria-label={`Copy: ${command}`} className="connect-cli-copy" data-connect-copy onClick={() => void copy()} type="button">
        {state === "copied" ? <CheckIcon aria-hidden="true" size={16} /> : <CopyIcon aria-hidden="true" size={16} />}
        <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : "Copy"}</span>
      </button>
    </div>
  );
}

function Step({ children, icon, title }: { children: ReactNode; icon: ReactNode; title: string }) {
  return (
    <section className="connect-cli-card" data-connect-step>
      <h2 className="m-0 flex items-center gap-2 font-sans text-base font-semibold tracking-tight">{icon}{title}</h2>
      {children}
    </section>
  );
}

const prose = "m-0 text-sm leading-relaxed text-[var(--org-muted)]";

export function ConnectCliBody({ plan }: { plan: CliConnectPlan | null }) {
  if (!plan) {
    return (
      <section className="connect-cli-card" data-connect-unavailable>
        <h2 className="m-0 flex items-center gap-2 font-sans text-base font-semibold"><InfoIcon aria-hidden="true" size={18} />This site is not set up for the command line</h2>
        <p className={prose}>This site does not publish the values the command line needs to sign in, so there is no command to copy here. Ask whoever runs {SITE_BRAND.appTitle} to switch it on.</p>
      </section>
    );
  }
  return (
    <div className="space-y-4" data-connect-cli>
      <section className="connect-cli-card" data-connect-about>
        <h2 className="m-0 flex items-center gap-2 font-sans text-base font-semibold"><UserCheckIcon aria-hidden="true" size={18} />What connecting does</h2>
        <p className={prose}>A reporting agent on a cloud computer, or the Papyrus command line on your own computer, has to sign in to {plan.site} before it can work here. When it does, it acts as you. It can read and change what you can read and change in this newsroom, and nothing more.</p>
        <p className={prose}>The sign-in renews itself and lasts days, not minutes. When it ends, run the same command again. Run <code className="connect-cli-inline">papyrus logout {plan.site}</code> on that computer to end it sooner.</p>
      </section>

      <Step icon={<DownloadIcon aria-hidden="true" size={18} />} title="Install the command line, once">
        <p className={prose}>Run this on the computer that will do the work: the agent&apos;s cloud computer, or your own. It needs Python 3.12 or newer. If you use uv, <code className="font-mono text-xs">{CLI_INSTALL_ALTERNATIVE}</code> does the same.</p>
        <CommandLine command={plan.install} label="Install command" />
      </Step>

      {plan.remoteCommand ? (
        <Step icon={<SmartphoneIcon aria-hidden="true" size={18} />} title="Connect an agent on a cloud computer, from your phone">
          <p className={prose}>An agent on a cloud computer has no browser, so you approve its sign-in from your phone or any other device of your own. Your password never reaches the agent; it gets only a sign-in session for this site.</p>
          <p className={prose}>Give the agent this command. It prints a link and a short code, then waits up to 10 minutes. Open the link, sign in with Google, check that the page shows the same code, and approve.</p>
          <CommandLine command={plan.remoteCommand} label="Sign-in command for an agent on a cloud computer" />
          <p className={prose} data-connect-remote-warning>Open the link yourself. Whoever approves first becomes the signed-in person.</p>
          <p className={prose} data-connect-remote-keyring>A cloud computer often has no keyring to keep the sign-in in. If so, the command says what to run first, and the sign-in then lasts until that computer restarts.</p>
        </Step>
      ) : (
        <section className="connect-cli-card" data-connect-remote-unavailable>
          <h2 className="m-0 flex items-center gap-2 font-sans text-base font-semibold"><SmartphoneIcon aria-hidden="true" size={18} />Connecting an agent from your phone is not switched on</h2>
          <p className={prose}>An agent on a cloud computer cannot connect to {plan.site} yet. Ask whoever runs {SITE_BRAND.appTitle} to switch on remote sign-in. Until then, the command line can only sign in on a computer with a browser.</p>
        </section>
      )}

      <Step icon={<LaptopIcon aria-hidden="true" size={18} />} title="Sign in on your own computer">
        <p className={prose}>On a computer with a browser, run this. Your browser opens; sign in with Google. When the browser says you are done, the command line is connected.</p>
        <CommandLine command={plan.browserCommand} label="Sign-in command for a computer with a browser" />
      </Step>

      <Step icon={<CheckIcon aria-hidden="true" size={18} />} title="Check that it worked">
        <p className={prose}>This shows who the command line is signed in as.</p>
        <CommandLine command={plan.checkCommand} label="Check command" />
      </Step>
    </div>
  );
}
