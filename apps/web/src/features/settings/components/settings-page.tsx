"use client";

import { useEffect, useState } from "react";

import type { AuthUser } from "@platform/shared-types";

import { useToast } from "@/components/providers/toast-provider";
import { AppFrame } from "@/components/shell/app-frame";
import { useTour } from "@/components/tour/tour-provider";
import { WELCOME_TOUR_ID, welcomeTour } from "@/components/tour/tours";
import { Icon } from "@/components/ui/icon";
import { AppearanceControls } from "@/features/preferences/components/appearance-controls";
import { AccountSecurity } from "@/features/settings/components/account-security";
import { ApiTokensPanel } from "@/features/settings/components/api-tokens-panel";
import { appConfig } from "@/lib/config";
import { cx } from "@/lib/utils";

type SettingsPageProps = {
  currentUser: AuthUser;
};

const TOUR_KEYS = ["pipewright.tour.welcome-v1", "pipewright.tour.studio-v1"];
const LAYOUT_KEYS = ["pipewright.rail.expanded", "pipewright.inspector.open"];

export function SettingsPageView({ currentUser }: SettingsPageProps) {
  const toast = useToast();
  const { start } = useTour();
  const [toursSeen, setToursSeen] = useState(0);

  const countSeenTours = () =>
    TOUR_KEYS.filter((key) => {
      try {
        return window.localStorage.getItem(key) === "done";
      } catch {
        return false;
      }
    }).length;

  useEffect(() => setToursSeen(countSeenTours()), []);

  const resetTours = () => {
    try {
      TOUR_KEYS.forEach((key) => window.localStorage.removeItem(key));
    } catch {
      /* ignore */
    }
    setToursSeen(0);
    toast.success("Tours reset", "They will run again the next time you open each screen.");
  };

  const resetLayout = () => {
    try {
      LAYOUT_KEYS.forEach((key) => window.localStorage.removeItem(key));
    } catch {
      /* ignore */
    }
    toast.info("Layout reset", "Reload the page to see the default panel positions.");
  };

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[{ label: "Settings" }]}
      statusItems={[
        { id: "user", label: "Signed in as", value: currentUser.username },
        { id: "role", label: "Role", value: currentUser.role },
      ]}
    >
      <div className="mx-auto max-w-3xl px-6 py-8">
        <header className="mb-7">
          <h1 className="text-[26px] font-semibold tracking-tight text-ink">Settings</h1>
          <p className="mt-2 text-[13px] text-ink-3">
            Your account, how this workspace looks, and how it behaves in this browser.
          </p>
        </header>

        <Section
          title="Appearance"
          description="Saved to your account, so it follows you to any machine you sign in from."
        >
          <div className="px-4 py-4">
            <AppearanceControls />
          </div>
        </Section>

        <Section title="Account" description="Who you are on this platform.">
          <Row label="Username" value={currentUser.username} />
          {currentUser.display_name ? (
            <Row label="Display name" value={currentUser.display_name} />
          ) : null}
          {currentUser.email ? <Row label="Email" value={currentUser.email} /> : null}
          <Row label="Role" value={currentUser.role} />
          <Row label="Status" value={currentUser.is_active ? "Active" : "Disabled"} />
        </Section>

        <Section
          title="Security"
          description="Change your password, and end sessions if one was left open."
        >
          <AccountSecurity />
        </Section>

        <Section
          title="API tokens"
          description="Long-lived credentials for scripts and other systems. Use these instead of a password. See the OpenAPI docs to call the API."
        >
          <ApiTokensPanel />
        </Section>

        <Section
          title="Guided tours"
          description="Interactive walkthroughs that point at the interface as they explain it."
        >
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
            <div>
              <div className="text-[13px] text-ink">
                {toursSeen} of {TOUR_KEYS.length} tours completed
              </div>
              <div className="mt-0.5 text-[11px] text-muted">
                Progress is stored in this browser only.
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => start(welcomeTour, WELCOME_TOUR_ID)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3 py-2 text-[12px] font-medium text-accent-ink transition hover:brightness-110"
              >
                <Icon name="sparkles" size={13} />
                Start tour
              </button>
              <button
                type="button"
                onClick={resetTours}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12px] text-ink transition hover:bg-surface-2"
              >
                <Icon name="refresh" size={13} />
                Reset
              </button>
            </div>
          </div>
        </Section>

        <Section title="Layout" description="Panel positions are remembered per browser.">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
            <div className="text-[13px] text-ink">
              Navigation and inspector state
              <div className="mt-0.5 text-[11px] text-muted">
                Restore the default collapsed rail and open inspector.
              </div>
            </div>
            <button
              type="button"
              onClick={resetLayout}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12px] text-ink transition hover:bg-surface-2"
            >
              <Icon name="refresh" size={13} />
              Reset layout
            </button>
          </div>
        </Section>

        <Section title="Connection" description="Where this interface sends its requests.">
          <Row label="API base URL" value={appConfig.apiBaseUrl} mono />
          <Row label="Application" value={appConfig.appName} />
          <div className="flex items-center justify-between px-4 py-3">
            <span className="text-[12px] text-muted">
              How accounts, credentials and data are protected.
            </span>
            <a
              href="https://github.com/harshkvpatil98/pipewright-data-platform/blob/main/docs/security.md"
              target="_blank"
              rel="noreferrer"
              className="text-[12px] text-[color:var(--accent)] transition hover:underline"
            >
              Security overview →
            </a>
          </div>
        </Section>

        <Section title="Keyboard shortcuts" description="Available anywhere in the application.">
          <Shortcut keys="⌘K / Ctrl K" action="Open the command palette" />
          <Shortcut keys="⌘\ / Ctrl \" action="Collapse or expand navigation" />
          <Shortcut keys="?" action="Replay the product tour" />
          <Shortcut keys="Esc" action="Close the palette, a menu, or a tour" />
        </Section>
      </div>
    </AppFrame>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5 overflow-hidden rounded-2xl border border-line bg-[color:var(--panel)]">
      <div className="border-b border-line px-4 py-3.5">
        <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
        <p className="mt-1 text-[12px] text-muted">{description}</p>
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3">
      <span className="text-[13px] text-ink-3">{label}</span>
      <span className={cx("truncate text-[13px] text-ink", mono && "font-mono text-[12px]")}>
        {value}
      </span>
    </div>
  );
}

function Shortcut({ keys, action }: { keys: string; action: string }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <span className="text-[13px] text-ink-2">{action}</span>
      <kbd className="shrink-0 rounded border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink-2">
        {keys}
      </kbd>
    </div>
  );
}
